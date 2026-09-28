from pathlib import Path

from ase.agent import propose_fix
from ase.apply_fix import apply_fix
from ase.models import FixProposal
from ase.verify import VerificationResult, verify_repository
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


def _load_proposal(checkpoints: list[Checkpoint]) -> FixProposal | None:
    """Reconstruct the proposal from a durable PROPOSE `after` checkpoint, if one exists."""
    for checkpoint in checkpoints:
        if checkpoint.step is StepName.PROPOSE and checkpoint.phase is CheckpointPhase.AFTER:
            return _proposal_from_state(checkpoint.state)
    return None


def run_job(store: JobStore, repo_root: Path, ticket: str, job_id: str) -> Job:
    """Run (or resume) a job through PROPOSE -> APPLY -> VERIFY.

    Recovery is structural: the store's checkpoints, not any in-memory
    state, determine which steps still need to run. A step that already has
    a durable `after` checkpoint is never re-entered.
    """
    job = store.get_job(job_id)
    if job is None:
        raise KeyError(job_id)

    if job.status in TERMINAL_JOB_STATUSES:
        return job

    checkpoints = store.list_checkpoints(job_id)
    resume_step = determine_resume_step(checkpoints)

    if resume_step is None:
        return store.update_job_status(job_id, JobStatus.SUCCEEDED)

    store.update_job_status(job_id, JobStatus.RUNNING)
    proposal = _load_proposal(checkpoints)

    if resume_step is StepName.PROPOSE:
        store.add_checkpoint(job_id, StepName.PROPOSE, CheckpointPhase.BEFORE)
        try:
            proposal = propose_fix(repo_root, ticket)
        except Exception:
            return store.update_job_status(job_id, JobStatus.FAILED)
        store.add_checkpoint(
            job_id, StepName.PROPOSE, CheckpointPhase.AFTER, _proposal_to_state(proposal)
        )
        resume_step = StepName.APPLY

    if resume_step is StepName.APPLY:
        assert proposal is not None
        store.add_checkpoint(job_id, StepName.APPLY, CheckpointPhase.BEFORE)
        try:
            apply_fix(repo_root, proposal)
        except Exception:
            return store.update_job_status(job_id, JobStatus.FAILED)
        store.add_checkpoint(
            job_id, StepName.APPLY, CheckpointPhase.AFTER, _proposal_to_state(proposal)
        )
        resume_step = StepName.VERIFY

    if resume_step is StepName.VERIFY:
        store.add_checkpoint(job_id, StepName.VERIFY, CheckpointPhase.BEFORE)
        try:
            result = verify_repository(repo_root)
        except Exception:
            return store.update_job_status(job_id, JobStatus.FAILED)
        store.add_checkpoint(
            job_id, StepName.VERIFY, CheckpointPhase.AFTER, _verification_to_state(result)
        )
        if not result.passed:
            return store.update_job_status(job_id, JobStatus.FAILED)

    return store.update_job_status(job_id, JobStatus.SUCCEEDED)
