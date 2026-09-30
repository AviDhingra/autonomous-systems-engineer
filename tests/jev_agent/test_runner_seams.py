"""Milestone 6: `run_job`'s `propose_fn` / `apply_fn` injection seams."""

from pathlib import Path

import pytest

from ase.models import FixProposal
from ase.verify import CheckResult, VerificationResult
from jev_agent import runner as runner_module
from jev_agent.models import CheckpointPhase, JobStatus, Judgment, StepName
from jev_agent.runner import run_job
from jev_agent.store import JobStore


def _passing(repo_root: Path) -> VerificationResult:
    return VerificationResult(
        checks=[CheckResult(name="pytest", command=["pytest"], returncode=0, stdout="", stderr="")]
    )


def _no_judge(state: dict[str, object]) -> Judgment:
    raise AssertionError("judge must not be consulted when VERIFY passes")


def _store(tmp_path: Path) -> JobStore:
    return JobStore(f"sqlite:///{tmp_path / 'seams_test.db'}")


def test_injected_propose_and_apply_are_called(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: object) -> object:
        raise AssertionError("Project 1 function called despite injection")

    monkeypatch.setattr(runner_module, "propose_fix", forbidden)
    monkeypatch.setattr(runner_module, "apply_fix", forbidden)
    calls: list[str] = []

    def propose(repo_root: Path, ticket: str) -> FixProposal:
        calls.append(f"propose:{ticket}")
        return FixProposal(file_path="a.py", explanation="e", new_content="new")

    def apply(repo_root: Path, proposal: FixProposal) -> object:
        calls.append(f"apply:{proposal.new_content}")
        return None

    store = _store(tmp_path)
    job = store.create_job("S")

    result = run_job(
        store,
        tmp_path,
        "ticket",
        job.id,
        verify_fn=_passing,
        judge_fn=_no_judge,
        propose_fn=propose,
        apply_fn=apply,
    )

    assert result.status is JobStatus.SUCCEEDED
    assert calls == ["propose:ticket", "apply:new"]
    after_steps = [
        c.step for c in store.list_checkpoints(job.id) if c.phase is CheckpointPhase.AFTER
    ]
    assert after_steps == [StepName.PROPOSE, StepName.APPLY, StepName.VERIFY]


def test_defaults_are_the_project1_functions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def propose(repo_root: Path, ticket: str) -> FixProposal:
        calls.append("propose_fix")
        return FixProposal(file_path="a.py", explanation="e", new_content="new")

    def apply(repo_root: Path, proposal: FixProposal) -> object:
        calls.append("apply_fix")
        return None

    # The defaults are looked up at call time, so patching the runner's
    # module-level Project 1 references proves they are what gets used.
    monkeypatch.setattr(runner_module, "propose_fix", propose)
    monkeypatch.setattr(runner_module, "apply_fix", apply)
    store = _store(tmp_path)
    job = store.create_job("S")

    run_job(store, tmp_path, "ticket", job.id, verify_fn=_passing, judge_fn=_no_judge)

    assert calls == ["propose_fix", "apply_fix"]


def test_runner_imports_the_real_project1_functions() -> None:
    from ase.agent import propose_fix
    from ase.apply_fix import apply_fix

    assert runner_module.propose_fix is propose_fix
    assert runner_module.apply_fix is apply_fix
