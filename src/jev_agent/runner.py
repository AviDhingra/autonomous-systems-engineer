import traceback
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from ase.agent import propose_fix
from ase.apply_fix import apply_fix
from ase.models import FixProposal
from ase.verify import VerificationResult, verify_repository
from jev_agent import judgment as judgment_module
from jev_agent import policy
from jev_agent.models import (
    NON_RUNNABLE_JOB_STATUSES,
    Checkpoint,
    CheckpointPhase,
    EscalationReason,
    EventType,
    HistoryEvent,
    Job,
    JobStatus,
    Judgment,
    Retryability,
    StepName,
)
from jev_agent.recovery import determine_resume_step
from jev_agent.store import JobStore

ProposeFn = Callable[[Path, str], FixProposal]
ApplyFn = Callable[[Path, FixProposal], object]
VerifyFn = Callable[[Path], VerificationResult]
JudgeFn = Callable[[dict[str, object]], Judgment]
ClockFn = Callable[[], datetime]

MAX_TRACEBACK_CHARS = 4000


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _proposal_to_state(proposal: FixProposal) -> dict[str, object]:
    return {
        "file_path": proposal.file_path,
        "explanation": proposal.explanation,
        "new_content": proposal.new_content,
    }


def _proposal_from_state(state: dict[str, object]) -> FixProposal:
    return FixProposal(
        file_path=str(state["file_path"]),
        explanation=str(state["explanation"]),
        new_content=str(state["new_content"]),
    )


def _failure_output(result: VerificationResult) -> str:
    """Human-readable text of the failing checks, for the JEV judgment."""
    parts = []
    for check in result.checks:
        if check.passed:
            continue
        parts.append(f"[{check.name}] exit {check.returncode}\n{check.stdout}{check.stderr}")
    return "\n".join(parts)


def _verification_to_state(result: VerificationResult) -> dict[str, object]:
    state: dict[str, object] = {
        "passed": result.passed,
        "checks": [
            {"name": check.name, "passed": check.passed, "returncode": check.returncode}
            for check in result.checks
        ],
    }
    if not result.passed:
        # Durable so a crash between VERIFY and the policy decision can still
        # judge and explain the failure on resume.
        limit = judgment_module.MAX_FAILURE_OUTPUT_CHARS
        state["failure_output"] = _failure_output(result)[:limit]
    return state


def _elapsed_seconds(job: Job, clock: ClockFn) -> float:
    created = job.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return (clock() - created).total_seconds()


def _fail_step(
    store: JobStore, job_id: str, attempt: int, step: StepName, error: Exception
) -> Job:
    """Record why a step raised, then mark the job FAILED. Without this the
    exception would be lost and a failed job would be undiagnosable."""
    trace = "".join(traceback.format_exception(error))
    store.append_history_event(
        job_id,
        attempt,
        EventType.STEP_ERROR,
        {
            "step": step.value,
            "error_type": type(error).__name__,
            "message": str(error),
            "traceback": trace[-MAX_TRACEBACK_CHARS:],
        },
    )
    return store.transition(
        job_id, JobStatus.FAILED, attempt, f"{step.value} raised {type(error).__name__}"
    )


def _judgment_events(store: JobStore, job_id: str) -> list[HistoryEvent]:
    return [
        event
        for event in store.list_history(job_id)
        if event.event_type is EventType.JEV_JUDGMENT
    ]


def _prior_failures(events: list[HistoryEvent]) -> list[str]:
    """Earlier attempts' failure outputs, rebuilt from durable history so a
    resumed job sees the same context an uninterrupted one would."""
    failures: list[str] = []
    for event in events:
        state = event.payload.get("input")
        if isinstance(state, dict):
            failures.append(str(state.get("failure_output", "")))
    return failures


def _consult_judge(
    judge: JudgeFn, state: dict[str, object]
) -> tuple[Judgment | None, dict[str, object]]:
    """Call JEV. Any failure means 'no judgment' (policy falls back), never a
    crashed or failed job. Returns the judgment and its history-shaped output."""
    try:
        result = judge(state)
    except Exception as error:
        return None, {"error": f"{type(error).__name__}: {error}"}
    return result, {
        "retryability": result.retryability.value,
        "confidence": result.confidence,
    }


def _judgment_from_output(output: object) -> Judgment | None:
    """Rebuild a recorded judgment from its history payload (None if the
    recorded consultation had failed)."""
    if not isinstance(output, dict) or "retryability" not in output:
        return None
    return Judgment(
        retryability=Retryability(str(output["retryability"])),
        confidence=float(output["confidence"]),
    )


def _load_proposal(checkpoints: list[Checkpoint], attempt: int) -> FixProposal | None:
    """Reconstruct the proposal from this attempt's durable PROPOSE `after`
    checkpoint, if one exists. Never looks at another attempt's proposal."""
    for checkpoint in checkpoints:
        if (
            checkpoint.step is StepName.PROPOSE
            and checkpoint.phase is CheckpointPhase.AFTER
            and checkpoint.attempt == attempt
        ):
            return _proposal_from_state(checkpoint.state)
    return None


def _saved_previous_content(checkpoints: list[Checkpoint], attempt: int) -> str | None:
    """The target file's original content as saved by this attempt's first
    APPLY `before` checkpoint (the one written before `apply_fix` ran)."""
    for checkpoint in checkpoints:
        if (
            checkpoint.step is StepName.APPLY
            and checkpoint.phase is CheckpointPhase.BEFORE
            and checkpoint.attempt == attempt
            and "previous_content" in checkpoint.state
        ):
            content = checkpoint.state["previous_content"]
            return None if content is None else str(content)
    return None


def _has_saved_previous_content(checkpoints: list[Checkpoint], attempt: int) -> bool:
    return any(
        checkpoint.step is StepName.APPLY
        and checkpoint.phase is CheckpointPhase.BEFORE
        and checkpoint.attempt == attempt
        and "previous_content" in checkpoint.state
        for checkpoint in checkpoints
    )


def _read_previous_content(repo_root: Path, file_path: str) -> str | None:
    """Byte-exact current content of the file APPLY is about to overwrite, or
    None if it cannot be read (apply_fix will then raise and fail the step)."""
    try:
        return (repo_root / file_path).read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _rollback_attempt(
    store: JobStore, repo_root: Path, job_id: str, attempt: int, checkpoints: list[Checkpoint]
) -> None:
    """Restore the file the failed attempt's APPLY wrote, so the next attempt
    investigates the original bug. Idempotent: rewriting the same bytes is
    harmless, and the ROLLBACK event is recorded once per attempt."""
    proposal = _load_proposal(checkpoints, attempt)
    previous = _saved_previous_content(checkpoints, attempt)
    if proposal is None or previous is None:
        return
    (repo_root / proposal.file_path).write_bytes(previous.encode("utf-8"))
    store.append_history_event_once(
        job_id, attempt, EventType.ROLLBACK, {"file_path": proposal.file_path}
    )


def _escalation_context(
    job: Job,
    elapsed_seconds: float,
    judgment: Judgment | None,
    failure_output: str,
) -> dict[str, object]:
    return {
        "retry_count": job.retry_count,
        "max_retries": job.budget.max_retries,
        "elapsed_seconds": elapsed_seconds,
        "max_wall_clock_seconds": job.budget.max_wall_clock_seconds,
        "judgment": (
            None
            if judgment is None
            else {
                "retryability": judgment.retryability.value,
                "confidence": judgment.confidence,
            }
        ),
        "failure_output": failure_output[: judgment_module.MAX_FAILURE_OUTPUT_CHARS],
    }


def _handle_verify_failure(
    store: JobStore,
    repo_root: Path,
    job: Job,
    attempt: int,
    failure_output: str,
    judge: JudgeFn,
    clock: ClockFn,
) -> Job | None:
    """Decide what follows a failed VERIFY and act on it.

    Returns the job if this ended the run (escalated or failed), or None if a
    retry has been set up and the caller should loop into the next attempt.

    A judgment already recorded for this attempt (a crash happened after
    consulting JEV but before acting) is reused rather than requested again.
    """
    events = _judgment_events(store, job.id)
    recorded = next((event for event in events if event.attempt == attempt), None)
    elapsed = _elapsed_seconds(job, clock)

    if recorded is not None:
        judgment = _judgment_from_output(recorded.payload.get("output"))
        outcome = policy.decide_verify_failure_outcome(
            job.retry_count, judgment, job.budget, elapsed
        )
    else:
        judge_state = judgment_module.build_judgment_state(
            failure_output, attempt, _prior_failures(events)
        )
        judgment, judge_output = _consult_judge(judge, judge_state)
        outcome = policy.decide_verify_failure_outcome(
            job.retry_count, judgment, job.budget, elapsed
        )
        store.append_history_event(
            job.id,
            attempt,
            EventType.JEV_JUDGMENT,
            {"input": judge_state, "output": judge_output, "outcome": outcome.value},
        )

    if outcome is policy.StepOutcome.ESCALATE:
        reason = policy.budget_exceeded(job.retry_count, elapsed, job.budget)
        store.escalate(
            job.id,
            attempt,
            reason or EscalationReason.JEV_NOT_RETRYABLE,
            _escalation_context(job, elapsed, judgment, failure_output),
        )
        return _require_job(store, job.id)

    if outcome is policy.StepOutcome.FAIL:
        return store.transition(job.id, JobStatus.FAILED, attempt, "policy decided fail")

    _rollback_attempt(store, repo_root, job.id, attempt, store.list_checkpoints(job.id))
    store.increment_retry_count(job.id, reason="verify failed; policy decided retry")
    store.transition(job.id, JobStatus.RETRYING, attempt, "retrying after verify failure")
    return None


def _require_job(store: JobStore, job_id: str) -> Job:
    job = store.get_job(job_id)
    if job is None:
        raise KeyError(job_id)
    return job


def _attempt_verify_state(checkpoints: list[Checkpoint], attempt: int) -> dict[str, object]:
    for checkpoint in checkpoints:
        if (
            checkpoint.step is StepName.VERIFY
            and checkpoint.phase is CheckpointPhase.AFTER
            and checkpoint.attempt == attempt
        ):
            return checkpoint.state
    return {}


def run_job(
    store: JobStore,
    repo_root: Path,
    ticket: str,
    job_id: str,
    verify_fn: VerifyFn | None = None,
    judge_fn: JudgeFn | None = None,
    clock: ClockFn | None = None,
    propose_fn: ProposeFn | None = None,
    apply_fn: ApplyFn | None = None,
) -> Job:
    """Run (or resume) a job through PROPOSE -> APPLY -> VERIFY, retrying a
    failed VERIFY (bounded by the job's budget) by restarting the whole
    attempt from PROPOSE, after rolling back the failed attempt's file change.

    Recovery is structural: the store's checkpoints, not any in-memory
    state, determine which steps still need to run. A step that already has
    an `after` checkpoint *for the current attempt* is never re-entered.
    Checkpoints from earlier attempts stay in the store as history but are
    never consulted for resume. If every step of the current attempt is
    complete, its VERIFY result decides: passed means SUCCEEDED, failed means
    the retry/escalate decision was interrupted and is made now.

    `verify_fn` defaults to `ase.verify.verify_repository`; it is an
    injection seam so callers (tests, demo scripts) can force deterministic
    VERIFY outcomes without depending on what the frontier model actually
    proposes.

    `judge_fn` defaults to the real JEV judgment and is consulted once per
    VERIFY failure. Its answer is one input to policy, is recorded in
    execution history before policy's outcome is acted on, and a judge that
    raises just means policy falls back to its fixed rule.

    `clock` (default: real UTC now) measures elapsed wall-clock time against
    the job's budget, and is injectable for deterministic tests.

    `propose_fn` and `apply_fn` default to `ase.agent.propose_fix` and
    `ase.apply_fix.apply_fix`; they are injection seams for simulated runs
    (the console's stories), which exercise the real governance path without
    calling the frontier model or touching `target/fleetops`.

    An exceeded budget or a confident not-retryable judgment escalates the
    job to `WAITING_ON_ESCALATION`; a raising step ends it `FAILED`. Both,
    like `SUCCEEDED`, are never re-run.
    """
    job = store.get_job(job_id)
    if job is None:
        raise KeyError(job_id)

    if job.status in NON_RUNNABLE_JOB_STATUSES:
        return job

    verify = verify_fn if verify_fn is not None else verify_repository
    judge = judge_fn if judge_fn is not None else judgment_module.judge_verify_failure
    now = clock if clock is not None else _utc_now
    propose = propose_fn if propose_fn is not None else propose_fix
    apply = apply_fn if apply_fn is not None else apply_fix

    while True:
        attempt = job.retry_count + 1
        checkpoints = store.list_checkpoints(job_id)
        resume_step = determine_resume_step(checkpoints, attempt)

        if resume_step is None:
            verify_state = _attempt_verify_state(checkpoints, attempt)
            if verify_state.get("passed") is True:
                return store.transition(job_id, JobStatus.SUCCEEDED, attempt, "verify passed")
            ended = _handle_verify_failure(
                store,
                repo_root,
                job,
                attempt,
                str(verify_state.get("failure_output", "")),
                judge,
                now,
            )
            if ended is not None:
                return ended
            job = _require_job(store, job_id)
            continue

        starting_retry = resume_step is StepName.PROPOSE and not any(
            checkpoint.attempt == attempt for checkpoint in checkpoints
        )
        if starting_retry and job.retry_count > 0:
            elapsed = _elapsed_seconds(job, now)
            if policy.wall_clock_exceeded(elapsed, job.budget):
                events = _judgment_events(store, job_id)
                last_failure = _prior_failures(events)[-1:] or [""]
                store.escalate(
                    job_id,
                    attempt,
                    EscalationReason.WALL_CLOCK_EXCEEDED,
                    _escalation_context(job, elapsed, None, last_failure[0]),
                )
                return _require_job(store, job_id)

        store.transition(job_id, JobStatus.RUNNING, attempt, "attempt started")
        proposal = _load_proposal(checkpoints, attempt)

        if resume_step is StepName.PROPOSE:
            store.add_checkpoint(job_id, StepName.PROPOSE, CheckpointPhase.BEFORE, attempt=attempt)
            try:
                proposal = propose(repo_root, ticket)
            except Exception as error:
                return _fail_step(store, job_id, attempt, StepName.PROPOSE, error)
            store.add_checkpoint(
                job_id,
                StepName.PROPOSE,
                CheckpointPhase.AFTER,
                _proposal_to_state(proposal),
                attempt=attempt,
            )
            resume_step = StepName.APPLY

        if resume_step is StepName.APPLY:
            assert proposal is not None
            # Save the file's original content *before* apply_fix overwrites it,
            # so a failed attempt can be rolled back. On re-entry after a crash
            # the saved value is reused: the file may already be overwritten.
            if not _has_saved_previous_content(checkpoints, attempt):
                store.add_checkpoint(
                    job_id,
                    StepName.APPLY,
                    CheckpointPhase.BEFORE,
                    {
                        "file_path": proposal.file_path,
                        "previous_content": _read_previous_content(
                            repo_root, proposal.file_path
                        ),
                    },
                    attempt=attempt,
                )
            else:
                store.add_checkpoint(
                    job_id, StepName.APPLY, CheckpointPhase.BEFORE, attempt=attempt
                )
            try:
                apply(repo_root, proposal)
            except Exception as error:
                return _fail_step(store, job_id, attempt, StepName.APPLY, error)
            store.add_checkpoint(
                job_id,
                StepName.APPLY,
                CheckpointPhase.AFTER,
                _proposal_to_state(proposal),
                attempt=attempt,
            )
            resume_step = StepName.VERIFY

        store.add_checkpoint(job_id, StepName.VERIFY, CheckpointPhase.BEFORE, attempt=attempt)
        try:
            result = verify(repo_root)
        except Exception as error:
            return _fail_step(store, job_id, attempt, StepName.VERIFY, error)
        store.add_checkpoint(
            job_id,
            StepName.VERIFY,
            CheckpointPhase.AFTER,
            _verification_to_state(result),
            attempt=attempt,
        )

        if result.passed:
            return store.transition(job_id, JobStatus.SUCCEEDED, attempt, "verify passed")

        ended = _handle_verify_failure(
            store, repo_root, job, attempt, _failure_output(result), judge, now
        )
        if ended is not None:
            return ended
        job = _require_job(store, job_id)
