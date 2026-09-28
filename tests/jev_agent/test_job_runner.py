from pathlib import Path

import pytest

from ase.models import FixProposal
from ase.verify import CheckResult, VerificationResult
from jev_agent import runner as runner_module
from jev_agent.models import CheckpointPhase, JobStatus, StepName
from jev_agent.runner import run_job
from jev_agent.store import JobStore

SCENARIO = "S02-unsupported-patch-fields"


def _store(tmp_path: Path) -> JobStore:
    return JobStore(f"sqlite:///{tmp_path / 'job_runner_test.db'}")


def _passing_verification() -> VerificationResult:
    return VerificationResult(
        checks=[CheckResult(name="pytest", command=["pytest"], returncode=0, stdout="", stderr="")]
    )


def test_clean_job_run_reaches_succeeded_with_one_checkpoint_pair_per_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    job = store.create_job(SCENARIO)
    assert job.status is JobStatus.PENDING

    proposal = FixProposal(
        file_path="target/fleetops/app/services/devices.py",
        explanation="Restore the unsupported-field guard.",
        new_content="REPLACED FILE CONTENTS\n",
    )
    apply_calls: list[FixProposal] = []

    def _record_apply(repo_root: Path, p: FixProposal) -> str:
        apply_calls.append(p)
        return "old content"

    monkeypatch.setattr(runner_module, "propose_fix", lambda repo_root, ticket: proposal)
    monkeypatch.setattr(runner_module, "apply_fix", _record_apply)
    monkeypatch.setattr(
        runner_module, "verify_repository", lambda repo_root: _passing_verification()
    )

    result = run_job(store, tmp_path, ticket="fix the bug", job_id=job.id)

    assert result.status is JobStatus.SUCCEEDED
    assert apply_calls == [proposal]

    checkpoints = store.list_checkpoints(job.id)
    by_step: dict[StepName, list[CheckpointPhase]] = {}
    for checkpoint in checkpoints:
        by_step.setdefault(checkpoint.step, []).append(checkpoint.phase)

    assert by_step[StepName.PROPOSE] == [CheckpointPhase.BEFORE, CheckpointPhase.AFTER]
    assert by_step[StepName.APPLY] == [CheckpointPhase.BEFORE, CheckpointPhase.AFTER]
    assert by_step[StepName.VERIFY] == [CheckpointPhase.BEFORE, CheckpointPhase.AFTER]


def test_job_run_fails_without_retry_when_propose_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    job = store.create_job(SCENARIO)

    def _boom(repo_root: Path, ticket: str) -> FixProposal:
        raise RuntimeError("Claude stopped before completing the investigation")

    monkeypatch.setattr(runner_module, "propose_fix", _boom)

    result = run_job(store, tmp_path, ticket="fix the bug", job_id=job.id)

    assert result.status is JobStatus.FAILED
    checkpoints = store.list_checkpoints(job.id)
    assert [c.phase for c in checkpoints if c.step is StepName.PROPOSE] == [
        CheckpointPhase.BEFORE
    ]
    assert not any(c.step is StepName.APPLY for c in checkpoints)


def test_completed_job_is_not_rerun(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = _store(tmp_path)
    job = store.create_job(SCENARIO)

    proposal = FixProposal(file_path="x.py", explanation="e", new_content="c")
    monkeypatch.setattr(runner_module, "propose_fix", lambda repo_root, ticket: proposal)
    monkeypatch.setattr(runner_module, "apply_fix", lambda repo_root, p: "old")
    monkeypatch.setattr(
        runner_module, "verify_repository", lambda repo_root: _passing_verification()
    )

    first = run_job(store, tmp_path, ticket="fix the bug", job_id=job.id)
    assert first.status is JobStatus.SUCCEEDED

    def _fail_if_called(*args: object, **kwargs: object) -> object:
        raise AssertionError("must not run again: job already reached a terminal status")

    monkeypatch.setattr(runner_module, "propose_fix", _fail_if_called)
    monkeypatch.setattr(runner_module, "apply_fix", _fail_if_called)
    monkeypatch.setattr(runner_module, "verify_repository", _fail_if_called)

    second = run_job(store, tmp_path, ticket="fix the bug", job_id=job.id)
    assert second.status is JobStatus.SUCCEEDED
