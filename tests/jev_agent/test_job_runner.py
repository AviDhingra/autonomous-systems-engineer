from collections.abc import Callable
from pathlib import Path

import pytest

from ase.models import FixProposal
from ase.verify import CheckResult, VerificationResult
from jev_agent import policy
from jev_agent import runner as runner_module
from jev_agent.models import CheckpointPhase, EventType, JobStatus, Judgment, Retryability, StepName
from jev_agent.runner import run_job
from jev_agent.store import JobStore

SCENARIO = "S02-unsupported-patch-fields"


def _store(tmp_path: Path) -> JobStore:
    return JobStore(f"sqlite:///{tmp_path / 'job_runner_test.db'}")


def _judge_returning(
    retryability: Retryability, confidence: float
) -> Callable[[dict[str, object]], Judgment]:
    def _judge(state: dict[str, object]) -> Judgment:
        return Judgment(retryability=retryability, confidence=confidence)

    return _judge


def _passing_verification() -> VerificationResult:
    return VerificationResult(
        checks=[CheckResult(name="pytest", command=["pytest"], returncode=0, stdout="", stderr="")]
    )


def _failing_verification() -> VerificationResult:
    return VerificationResult(
        checks=[
            CheckResult(name="pytest", command=["pytest"], returncode=1, stdout="", stderr="boom")
        ]
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

    (event,) = store.list_history(job.id)
    assert event.event_type is EventType.STEP_ERROR
    assert event.attempt == 1
    assert event.payload["step"] == "propose"
    assert event.payload["error_type"] == "RuntimeError"
    assert "stopped before completing" in str(event.payload["message"])
    assert "RuntimeError" in str(event.payload["traceback"])


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


# --- Milestone 2: bounded retry on VERIFY failure ---


def _propose_with_attempt_marker() -> tuple[list[str], Callable[[Path, str], FixProposal]]:
    """A propose_fix stand-in whose output is distinguishable per call, so
    tests can assert an attempt's APPLY used that same attempt's proposal
    and not a stale one from an earlier attempt."""
    calls: list[str] = []

    def _propose(repo_root: Path, ticket: str) -> FixProposal:
        calls.append(ticket)
        n = len(calls)
        return FixProposal(
            file_path="x.py", explanation=f"attempt {n}", new_content=f"content-{n}"
        )

    return calls, _propose


def test_verify_that_always_fails_ends_failed_after_bounded_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    job = store.create_job(SCENARIO)

    propose_calls, _propose = _propose_with_attempt_marker()
    apply_calls: list[FixProposal] = []

    def _apply(repo_root: Path, proposal: FixProposal) -> str:
        apply_calls.append(proposal)
        return "old"

    monkeypatch.setattr(runner_module, "propose_fix", _propose)
    monkeypatch.setattr(runner_module, "apply_fix", _apply)

    result = run_job(
        store,
        tmp_path,
        ticket="fix the bug",
        job_id=job.id,
        verify_fn=lambda repo_root: _failing_verification(),
        judge_fn=_judge_returning(Retryability.RETRYABLE, 0.9),
    )

    total_attempts = policy.MAX_VERIFY_RETRIES + 1
    assert result.status is JobStatus.FAILED
    assert result.retry_count == policy.MAX_VERIFY_RETRIES
    assert len(propose_calls) == total_attempts
    assert len(apply_calls) == total_attempts

    checkpoints = store.list_checkpoints(job.id)
    completed_steps_by_attempt: dict[int, set[StepName]] = {}
    for checkpoint in checkpoints:
        if checkpoint.phase is CheckpointPhase.AFTER:
            completed_steps_by_attempt.setdefault(checkpoint.attempt, set()).add(checkpoint.step)

    assert set(completed_steps_by_attempt) == set(range(1, total_attempts + 1))
    for steps in completed_steps_by_attempt.values():
        assert steps == {StepName.PROPOSE, StepName.APPLY, StepName.VERIFY}


def test_verify_that_fails_once_then_succeeds_resolves_after_two_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    job = store.create_job(SCENARIO)

    propose_calls, _propose = _propose_with_attempt_marker()
    apply_calls: list[FixProposal] = []

    def _apply(repo_root: Path, proposal: FixProposal) -> str:
        apply_calls.append(proposal)
        return "old"

    verify_results = [_failing_verification(), _passing_verification()]

    def _verify(repo_root: Path) -> VerificationResult:
        return verify_results.pop(0)

    monkeypatch.setattr(runner_module, "propose_fix", _propose)
    monkeypatch.setattr(runner_module, "apply_fix", _apply)

    result = run_job(
        store,
        tmp_path,
        ticket="fix the bug",
        job_id=job.id,
        verify_fn=_verify,
        judge_fn=_judge_returning(Retryability.RETRYABLE, 0.9),
    )

    assert result.status is JobStatus.SUCCEEDED
    assert result.retry_count == 1
    assert len(propose_calls) == 2
    assert len(apply_calls) == 2

    # Idempotency across attempts: each attempt's APPLY used that same
    # attempt's own fresh proposal, never a stale one from the failed attempt.
    assert apply_calls[0].explanation == "attempt 1"
    assert apply_calls[1].explanation == "attempt 2"
    assert apply_calls[0] != apply_calls[1]


def test_recovery_mid_retry_resumes_attempt_two_without_rerunning_attempt_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Interrupt after attempt 2's PROPOSE completes but before attempt 2's
    APPLY starts. Resume must re-enter attempt 2 at APPLY, never touch
    attempt 1's checkpoints, and never call propose_fix again."""
    store = _store(tmp_path)
    job = store.create_job(SCENARIO)

    attempt1_state: dict[str, object] = {
        "file_path": "x.py",
        "explanation": "attempt 1",
        "new_content": "content-1",
    }
    store.add_checkpoint(job.id, StepName.PROPOSE, CheckpointPhase.BEFORE, attempt=1)
    store.add_checkpoint(
        job.id, StepName.PROPOSE, CheckpointPhase.AFTER, attempt1_state, attempt=1
    )
    store.add_checkpoint(job.id, StepName.APPLY, CheckpointPhase.BEFORE, attempt=1)
    store.add_checkpoint(job.id, StepName.APPLY, CheckpointPhase.AFTER, attempt1_state, attempt=1)
    store.add_checkpoint(job.id, StepName.VERIFY, CheckpointPhase.BEFORE, attempt=1)
    store.add_checkpoint(
        job.id,
        StepName.VERIFY,
        CheckpointPhase.AFTER,
        {"passed": False, "checks": []},
        attempt=1,
    )
    store.increment_retry_count(job.id)

    attempt2_state: dict[str, object] = {
        "file_path": "x.py",
        "explanation": "attempt 2",
        "new_content": "content-2",
    }
    store.add_checkpoint(job.id, StepName.PROPOSE, CheckpointPhase.BEFORE, attempt=2)
    store.add_checkpoint(
        job.id, StepName.PROPOSE, CheckpointPhase.AFTER, attempt2_state, attempt=2
    )
    store.update_job_status(job.id, JobStatus.RETRYING)

    def _fail_if_called(*args: object, **kwargs: object) -> object:
        raise AssertionError("must not re-propose: attempt 2's PROPOSE is already checkpointed")

    apply_calls: list[FixProposal] = []

    def _apply(repo_root: Path, proposal: FixProposal) -> str:
        apply_calls.append(proposal)
        return "old"

    monkeypatch.setattr(runner_module, "propose_fix", _fail_if_called)
    monkeypatch.setattr(runner_module, "apply_fix", _apply)

    result = run_job(
        store,
        tmp_path,
        ticket="unused",
        job_id=job.id,
        verify_fn=lambda repo_root: _passing_verification(),
    )

    assert result.status is JobStatus.SUCCEEDED
    assert len(apply_calls) == 1
    assert apply_calls[0].explanation == "attempt 2"

    checkpoints = store.list_checkpoints(job.id)
    attempt_one_checkpoints = [c for c in checkpoints if c.attempt == 1]
    assert len(attempt_one_checkpoints) == 6
    attempt_one_after_steps = {
        c.step for c in attempt_one_checkpoints if c.phase is CheckpointPhase.AFTER
    }
    assert attempt_one_after_steps == {StepName.PROPOSE, StepName.APPLY, StepName.VERIFY}


# --- Milestone 3: JEV judgment consulted on VERIFY failure ---


def _wire_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[str], list[FixProposal]]:
    propose_calls, _propose = _propose_with_attempt_marker()
    apply_calls: list[FixProposal] = []

    def _apply(repo_root: Path, proposal: FixProposal) -> str:
        apply_calls.append(proposal)
        return "old"

    monkeypatch.setattr(runner_module, "propose_fix", _propose)
    monkeypatch.setattr(runner_module, "apply_fix", _apply)
    return propose_calls, apply_calls


def _run_failing(
    tmp_path: Path, judge_fn: Callable[[dict[str, object]], Judgment]
) -> tuple[JobStore, str]:
    store = _store(tmp_path)
    job = store.create_job(SCENARIO)
    result = run_job(
        store,
        tmp_path,
        ticket="fix the bug",
        job_id=job.id,
        verify_fn=lambda repo_root: _failing_verification(),
        judge_fn=judge_fn,
    )
    assert result.status is JobStatus.FAILED
    return store, job.id


def test_confident_not_retryable_fails_after_one_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    propose_calls, _ = _wire_pipeline(monkeypatch)

    store, job_id = _run_failing(tmp_path, _judge_returning(Retryability.NOT_RETRYABLE, 0.9))

    assert len(propose_calls) == 1
    job = store.get_job(job_id)
    assert job is not None and job.retry_count == 0
    history = store.list_history(job_id)
    assert len(history) == 1
    assert history[0].payload["outcome"] == policy.StepOutcome.FAIL.value


def test_confident_retryable_still_bounded_by_the_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Policy, not JEV, sets the outcome: a judge that always says RETRYABLE
    cannot push the job past the retry cap."""
    propose_calls, _ = _wire_pipeline(monkeypatch)

    store, job_id = _run_failing(tmp_path, _judge_returning(Retryability.RETRYABLE, 0.99))

    assert len(propose_calls) == policy.MAX_VERIFY_RETRIES + 1
    job = store.get_job(job_id)
    assert job is not None and job.retry_count == policy.MAX_VERIFY_RETRIES
    outcomes = [e.payload["outcome"] for e in store.list_history(job_id)]
    assert outcomes == ["retry"] * policy.MAX_VERIFY_RETRIES + ["fail"]


def test_judge_that_raises_falls_back_to_fixed_rule_and_records_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    propose_calls, _ = _wire_pipeline(monkeypatch)

    def _boom(state: dict[str, object]) -> Judgment:
        raise TimeoutError("jev unreachable")

    store, job_id = _run_failing(tmp_path, _boom)

    assert len(propose_calls) == policy.MAX_VERIFY_RETRIES + 1
    history = store.list_history(job_id)
    assert len(history) == policy.MAX_VERIFY_RETRIES + 1
    output = history[0].payload["output"]
    assert isinstance(output, dict) and "TimeoutError" in str(output["error"])


def test_low_confidence_judgment_falls_back_to_fixed_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    propose_calls, _ = _wire_pipeline(monkeypatch)

    _run_failing(tmp_path, _judge_returning(Retryability.NOT_RETRYABLE, 0.1))

    assert len(propose_calls) == policy.MAX_VERIFY_RETRIES + 1


def test_history_event_records_input_output_and_outcome_per_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire_pipeline(monkeypatch)

    store, job_id = _run_failing(tmp_path, _judge_returning(Retryability.RETRYABLE, 0.9))

    history = store.list_history(job_id)
    assert all(e.event_type is EventType.JEV_JUDGMENT for e in history)
    assert [e.attempt for e in history] == [1, 2, 3]
    first = history[0].payload
    assert isinstance(first["input"], dict)
    assert "boom" in str(first["input"]["failure_output"])
    assert first["input"]["prior_failures"] == []
    assert first["output"] == {"retryability": "retryable", "confidence": 0.9}
    # Later attempts see earlier failures, rebuilt from history.
    second_input = history[1].payload["input"]
    assert isinstance(second_input, dict) and len(second_input["prior_failures"]) == 1


def test_no_history_event_when_verification_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire_pipeline(monkeypatch)
    store = _store(tmp_path)
    job = store.create_job(SCENARIO)

    def _fail_if_called(state: dict[str, object]) -> Judgment:
        raise AssertionError("JEV must only be consulted on a VERIFY failure")

    result = run_job(
        store,
        tmp_path,
        ticket="t",
        job_id=job.id,
        verify_fn=lambda repo_root: _passing_verification(),
        judge_fn=_fail_if_called,
    )

    assert result.status is JobStatus.SUCCEEDED
    assert store.list_history(job.id) == []


def test_apply_and_verify_exceptions_are_recorded_as_step_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _apply_boom(repo_root: Path, proposal: FixProposal) -> str:
        raise OSError("disk full")

    _, _propose = _propose_with_attempt_marker()
    monkeypatch.setattr(runner_module, "propose_fix", _propose)
    monkeypatch.setattr(runner_module, "apply_fix", _apply_boom)
    store = _store(tmp_path)
    job = store.create_job(SCENARIO)
    assert run_job(store, tmp_path, "t", job.id).status is JobStatus.FAILED
    (event,) = store.list_history(job.id)
    assert (event.payload["step"], event.payload["error_type"]) == ("apply", "OSError")

    def _verify_boom(repo_root: Path) -> VerificationResult:
        raise TimeoutError("checks hung")

    monkeypatch.setattr(runner_module, "apply_fix", lambda repo_root, p: "old")
    store2 = JobStore(f"sqlite:///{tmp_path / 'second.db'}")
    job2 = store2.create_job(SCENARIO)
    result = run_job(store2, tmp_path, "t", job2.id, verify_fn=_verify_boom)
    assert result.status is JobStatus.FAILED
    (event2,) = store2.list_history(job2.id)
    assert (event2.payload["step"], event2.payload["error_type"]) == ("verify", "TimeoutError")
