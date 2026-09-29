from pathlib import Path

import pytest

from ase.verify import CheckResult, VerificationResult
from jev_agent import runner as runner_module
from jev_agent.models import (
    DEFAULT_MAX_RETRIES,
    Checkpoint,
    CheckpointPhase,
    Job,
    JobStatus,
    StepName,
)
from jev_agent.recovery import determine_resume_step
from jev_agent.runner import run_job
from jev_agent.store import JobStore


def test_resume_step_is_propose_with_no_checkpoints() -> None:
    assert determine_resume_step([], attempt=1) is StepName.PROPOSE


def test_resume_step_is_apply_once_propose_completed() -> None:
    checkpoints = [_checkpoint(StepName.PROPOSE, CheckpointPhase.AFTER)]

    assert determine_resume_step(checkpoints, attempt=1) is StepName.APPLY


def test_resume_step_is_verify_once_propose_and_apply_completed() -> None:
    checkpoints = [
        _checkpoint(StepName.PROPOSE, CheckpointPhase.AFTER),
        _checkpoint(StepName.APPLY, CheckpointPhase.AFTER),
    ]

    assert determine_resume_step(checkpoints, attempt=1) is StepName.VERIFY


def test_resume_step_is_none_once_all_steps_completed() -> None:
    checkpoints = [
        _checkpoint(StepName.PROPOSE, CheckpointPhase.AFTER),
        _checkpoint(StepName.APPLY, CheckpointPhase.AFTER),
        _checkpoint(StepName.VERIFY, CheckpointPhase.AFTER),
    ]

    assert determine_resume_step(checkpoints, attempt=1) is None


def test_a_step_with_only_a_before_checkpoint_is_not_treated_as_completed() -> None:
    checkpoints = [
        _checkpoint(StepName.PROPOSE, CheckpointPhase.AFTER),
        _checkpoint(StepName.APPLY, CheckpointPhase.BEFORE),
    ]

    assert determine_resume_step(checkpoints, attempt=1) is StepName.APPLY


def test_a_prior_attempts_completed_steps_do_not_satisfy_the_current_attempt() -> None:
    """A retry restarts from PROPOSE: attempt 1's completed steps must never
    be mistaken for attempt 2's progress."""
    checkpoints = [
        _checkpoint(StepName.PROPOSE, CheckpointPhase.AFTER, attempt=1),
        _checkpoint(StepName.APPLY, CheckpointPhase.AFTER, attempt=1),
        _checkpoint(StepName.VERIFY, CheckpointPhase.AFTER, attempt=1),
    ]

    assert determine_resume_step(checkpoints, attempt=2) is StepName.PROPOSE


def test_resume_within_a_retry_only_considers_that_attempts_checkpoints() -> None:
    """Interrupted mid-attempt-2 (PROPOSE done, APPLY not started) resumes at
    APPLY for attempt 2, ignoring attempt 1's history entirely."""
    checkpoints = [
        _checkpoint(StepName.PROPOSE, CheckpointPhase.AFTER, attempt=1),
        _checkpoint(StepName.APPLY, CheckpointPhase.AFTER, attempt=1),
        _checkpoint(StepName.VERIFY, CheckpointPhase.AFTER, attempt=1),
        _checkpoint(StepName.PROPOSE, CheckpointPhase.AFTER, attempt=2),
    ]

    assert determine_resume_step(checkpoints, attempt=2) is StepName.APPLY


def _checkpoint(step: StepName, phase: CheckpointPhase, attempt: int = 1) -> Checkpoint:
    return Checkpoint(id=1, job_id="job", step=step, phase=phase, attempt=attempt)


# --- Milestone 1 exit-criteria proof: kill after APPLY, resume at VERIFY ---


def _store(tmp_path: Path) -> JobStore:
    return JobStore(f"sqlite:///{tmp_path / 'recovery_test.db'}")


def _seed_job_interrupted_after_apply(store: JobStore, attempt: int = 1) -> Job:
    """Build a job whose PROPOSE and APPLY steps are durably checkpointed
    for `attempt`, but whose VERIFY step never started — exactly the state a
    process crash right after `apply_fix` (and before `verify_repository`
    runs) would leave behind."""
    job = store.create_job("S02-unsupported-patch-fields")
    store.update_job_status(job.id, JobStatus.RUNNING)

    proposal_state: dict[str, object] = {
        "file_path": "target/fleetops/app/services/devices.py",
        "explanation": "Restore the unsupported-field guard.",
        "new_content": "REPLACED FILE CONTENTS\n",
    }
    store.add_checkpoint(job.id, StepName.PROPOSE, CheckpointPhase.BEFORE, attempt=attempt)
    store.add_checkpoint(
        job.id, StepName.PROPOSE, CheckpointPhase.AFTER, proposal_state, attempt=attempt
    )
    store.add_checkpoint(job.id, StepName.APPLY, CheckpointPhase.BEFORE, attempt=attempt)
    store.add_checkpoint(
        job.id, StepName.APPLY, CheckpointPhase.AFTER, proposal_state, attempt=attempt
    )

    return job


def test_resuming_after_apply_skips_propose_and_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    job = _seed_job_interrupted_after_apply(store)

    def _fail_if_called(*args: object, **kwargs: object) -> object:
        raise AssertionError("must not be called on resume: already checkpointed")

    passing_result = VerificationResult(
        checks=[CheckResult(name="pytest", command=["pytest"], returncode=0, stdout="", stderr="")]
    )

    monkeypatch.setattr(runner_module, "propose_fix", _fail_if_called)
    monkeypatch.setattr(runner_module, "apply_fix", _fail_if_called)
    monkeypatch.setattr(runner_module, "verify_repository", lambda repo_root: passing_result)

    result = run_job(store, tmp_path, ticket="unused", job_id=job.id)

    assert result.status is JobStatus.SUCCEEDED

    checkpoints = store.list_checkpoints(job.id)
    verify_checkpoints = [c for c in checkpoints if c.step is StepName.VERIFY]
    assert [c.phase for c in verify_checkpoints] == [
        CheckpointPhase.BEFORE,
        CheckpointPhase.AFTER,
    ]


def test_resuming_after_apply_escalates_job_if_verify_fails_and_retries_are_exhausted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A VERIFY failure doesn't fail the job outright anymore (Milestone 2:
    it's bounded-retried first — see test_job_runner.py). Seed the job at
    the retry cap so this resume still exercises the Milestone 1 guarantee:
    resuming after APPLY never re-proposes or re-applies."""
    store = _store(tmp_path)
    job = _seed_job_interrupted_after_apply(store, attempt=DEFAULT_MAX_RETRIES + 1)
    for _ in range(DEFAULT_MAX_RETRIES):
        store.increment_retry_count(job.id)

    def _fail_if_called(*args: object, **kwargs: object) -> object:
        raise AssertionError("must not be called on resume: already checkpointed")

    failing_result = VerificationResult(
        checks=[
            CheckResult(name="pytest", command=["pytest"], returncode=1, stdout="", stderr="boom")
        ]
    )

    monkeypatch.setattr(runner_module, "propose_fix", _fail_if_called)
    monkeypatch.setattr(runner_module, "apply_fix", _fail_if_called)
    monkeypatch.setattr(runner_module, "verify_repository", lambda repo_root: failing_result)

    def _no_judgment(state: dict[str, object]) -> object:
        raise RuntimeError("no JEV in this test")

    result = run_job(
        store,
        tmp_path,
        ticket="unused",
        job_id=job.id,
        judge_fn=_no_judgment,  # type: ignore[arg-type]
    )

    assert result.status is JobStatus.WAITING_ON_ESCALATION
