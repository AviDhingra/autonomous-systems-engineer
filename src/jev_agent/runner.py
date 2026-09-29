import traceback
from collections.abc import Callable
from pathlib import Path

from ase.agent import propose_fix
from ase.apply_fix import apply_fix
from ase.models import FixProposal
from ase.verify import VerificationResult, verify_repository
from jev_agent import judgment as judgment_module
from jev_agent import policy
from jev_agent.models import (
    TERMINAL_JOB_STATUSES,
    Checkpoint,
    CheckpointPhase,
    EventType,
    Job,
    JobStatus,
    Judgment,
    StepName,
)
from jev_agent.recovery import determine_resume_step
from jev_agent.store import JobStore

VerifyFn = Callable[[Path], VerificationResult]
JudgeFn = Callable[[dict[str, object]], Judgment]


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


def _verification_to_state(result: VerificationResult) -> dict[str, object]:
    return {
        "passed": result.passed,
        "checks": [
            {"name": check.name, "passed": check.passed, "returncode": check.returncode}
            for check in result.checks
        ],
    }


def _failure_output(result: VerificationResult) -> str:
    """Human-readable text of the failing checks, for the JEV judgment."""
    parts = []
    for check in result.checks:
        if check.passed:
            continue
        parts.append(f"[{check.name}] exit {check.returncode}\n{check.stdout}{check.stderr}")
    return "\n".join(parts)


MAX_TRACEBACK_CHARS = 4000


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
    return store.update_job_status(job_id, JobStatus.FAILED)


def _prior_failures(store: JobStore, job_id: str) -> list[str]:
    """Earlier attempts' failure outputs, rebuilt from durable history so a
    resumed job sees the same context an uninterrupted one would."""
    failures: list[str] = []
    for event in store.list_history(job_id):
        if event.event_type is EventType.JEV_JUDGMENT:
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


def run_job(
    store: JobStore,
    repo_root: Path,
    ticket: str,
    job_id: str,
    verify_fn: VerifyFn | None = None,
    judge_fn: JudgeFn | None = None,
) -> Job:
    """Run (or resume) a job through PROPOSE -> APPLY -> VERIFY, retrying a
    failed VERIFY (bounded by deterministic policy) by restarting the whole
    attempt from PROPOSE.

    Recovery is structural: the store's checkpoints, not any in-memory
    state, determine which steps still need to run. A step that already has
    an `after` checkpoint *for the current attempt* is never re-entered.
    Checkpoints from earlier attempts stay in the store as history but are
    never consulted for resume.

    `verify_fn` defaults to `ase.verify.verify_repository`; it is an
    injection seam so callers (tests, demo scripts) can force deterministic
    VERIFY outcomes without depending on what the frontier model actually
    proposes.

    `judge_fn` defaults to the real JEV judgment and is consulted once per
    VERIFY failure. Its answer is one input to policy, is recorded in
    execution history before policy's outcome is acted on, and a judge that
    raises just means policy falls back to its fixed rule.
    """
    job = store.get_job(job_id)
    if job is None:
        raise KeyError(job_id)

    if job.status in TERMINAL_JOB_STATUSES:
        return job

    verify = verify_fn if verify_fn is not None else verify_repository
    judge = judge_fn if judge_fn is not None else judgment_module.judge_verify_failure

    while True:
        attempt = job.retry_count + 1
        checkpoints = store.list_checkpoints(job_id)
        resume_step = determine_resume_step(checkpoints, attempt)

        if resume_step is None:
            return store.update_job_status(job_id, JobStatus.SUCCEEDED)

        store.update_job_status(job_id, JobStatus.RUNNING)
        proposal = _load_proposal(checkpoints, attempt)

        if resume_step is StepName.PROPOSE:
            store.add_checkpoint(job_id, StepName.PROPOSE, CheckpointPhase.BEFORE, attempt=attempt)
            try:
                proposal = propose_fix(repo_root, ticket)
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
            store.add_checkpoint(job_id, StepName.APPLY, CheckpointPhase.BEFORE, attempt=attempt)
            try:
                apply_fix(repo_root, proposal)
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
            return store.update_job_status(job_id, JobStatus.SUCCEEDED)

        judge_state = judgment_module.build_judgment_state(
            _failure_output(result), attempt, _prior_failures(store, job_id)
        )
        judgment, judge_output = _consult_judge(judge, judge_state)
        outcome = policy.decide_verify_failure_outcome(job.retry_count, judgment)
        store.append_history_event(
            job_id,
            attempt,
            EventType.JEV_JUDGMENT,
            {"input": judge_state, "output": judge_output, "outcome": outcome.value},
        )
        if outcome is not policy.StepOutcome.RETRY:
            return store.update_job_status(job_id, JobStatus.FAILED)

        job = store.increment_retry_count(job_id)
        store.update_job_status(job_id, JobStatus.RETRYING)
