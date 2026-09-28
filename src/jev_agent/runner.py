from collections.abc import Callable
from pathlib import Path

from ase.agent import propose_fix
from ase.apply_fix import apply_fix
from ase.models import FixProposal
from ase.verify import VerificationResult, verify_repository
from jev_agent import policy
from jev_agent.models import (
    TERMINAL_JOB_STATUSES,
    Checkpoint,
    CheckpointPhase,
    Job,
    JobStatus,
    StepName,
)
from jev_agent.recovery import determine_resume_step
from jev_agent.store import JobStore

VerifyFn = Callable[[Path], VerificationResult]


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
    """
    job = store.get_job(job_id)
    if job is None:
        raise KeyError(job_id)

    if job.status in TERMINAL_JOB_STATUSES:
        return job

    verify = verify_fn if verify_fn is not None else verify_repository

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
            except Exception:
                return store.update_job_status(job_id, JobStatus.FAILED)
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
            except Exception:
                return store.update_job_status(job_id, JobStatus.FAILED)
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
        except Exception:
            return store.update_job_status(job_id, JobStatus.FAILED)
        store.add_checkpoint(
            job_id,
            StepName.VERIFY,
            CheckpointPhase.AFTER,
            _verification_to_state(result),
            attempt=attempt,
        )

        if result.passed:
            return store.update_job_status(job_id, JobStatus.SUCCEEDED)

        outcome = policy.decide_verify_failure_outcome(job.retry_count)
        if outcome is not policy.StepOutcome.RETRY:
            return store.update_job_status(job_id, JobStatus.FAILED)

        job = store.increment_retry_count(job_id)
        store.update_job_status(job_id, JobStatus.RETRYING)
