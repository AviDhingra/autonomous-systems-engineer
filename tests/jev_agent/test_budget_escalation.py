"""Milestone 4: budgets, escalation, crash recovery of a failed VERIFY,
rollback before retry, and history completeness. Uses a fake clock and fake
judge throughout: no network, no real waiting."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ase.models import FixProposal
from ase.verify import CheckResult, VerificationResult
from jev_agent import runner as runner_module
from jev_agent.models import (
    DEFAULT_MAX_RETRIES,
    Budget,
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
from jev_agent.runner import run_job
from jev_agent.store import JobStore

SCENARIO = "S02-unsupported-patch-fields"
TARGET_FILE = "target/fleetops/app/mod.py"
ORIGINAL = b"line1\r\nline2\nline3\n"


class FakeClock:
    """Real now plus a controllable offset, so elapsed time is deterministic
    relative to a job's real `created_at`."""

    def __init__(self) -> None:
        self.offset = 0.0

    def __call__(self) -> datetime:
        return datetime.now(UTC) + timedelta(seconds=self.offset)


def _store(tmp_path: Path) -> JobStore:
    return JobStore(f"sqlite:///{tmp_path / 'm4_test.db'}")


def _failing() -> VerificationResult:
    return VerificationResult(
        checks=[
            CheckResult(name="pytest", command=["pytest"], returncode=1, stdout="", stderr="boom")
        ]
    )


def _passing() -> VerificationResult:
    return VerificationResult(
        checks=[CheckResult(name="pytest", command=["pytest"], returncode=0, stdout="", stderr="")]
    )


def _judge(
    retryability: Retryability, confidence: float
) -> Callable[[dict[str, object]], Judgment]:
    return lambda state: Judgment(retryability=retryability, confidence=confidence)


def _no_judge(state: dict[str, object]) -> Judgment:
    raise RuntimeError("JEV unavailable")


def _events(store: JobStore, job_id: str, event_type: EventType) -> list[HistoryEvent]:
    return [e for e in store.list_history(job_id) if e.event_type is event_type]


def _wire_mock_pipeline(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Stand-in propose/apply that touch no files. Returns the propose calls."""
    calls: list[int] = []

    def _propose(repo_root: Path, ticket: str) -> FixProposal:
        calls.append(len(calls) + 1)
        return FixProposal(file_path="x.py", explanation="e", new_content=f"c{len(calls)}")

    monkeypatch.setattr(runner_module, "propose_fix", _propose)
    monkeypatch.setattr(runner_module, "apply_fix", lambda repo_root, p: "old")
    return calls


def _seed_failed_attempt(
    store: JobStore, job: Job, attempt: int, *, previous_content: str | None = None
) -> None:
    """A whole attempt on disk whose VERIFY failed and whose outcome was never
    acted on (as if the process died right after the VERIFY checkpoint)."""
    state: dict[str, object] = {
        "file_path": TARGET_FILE,
        "explanation": "e",
        "new_content": "NEW",
    }
    store.add_checkpoint(job.id, StepName.PROPOSE, CheckpointPhase.BEFORE, attempt=attempt)
    store.add_checkpoint(job.id, StepName.PROPOSE, CheckpointPhase.AFTER, state, attempt=attempt)
    before: dict[str, object] = {"file_path": TARGET_FILE}
    if previous_content is not None:
        before["previous_content"] = previous_content
    store.add_checkpoint(job.id, StepName.APPLY, CheckpointPhase.BEFORE, before, attempt=attempt)
    store.add_checkpoint(job.id, StepName.APPLY, CheckpointPhase.AFTER, state, attempt=attempt)
    store.add_checkpoint(job.id, StepName.VERIFY, CheckpointPhase.BEFORE, attempt=attempt)
    store.add_checkpoint(
        job.id,
        StepName.VERIFY,
        CheckpointPhase.AFTER,
        {"passed": False, "checks": [], "failure_output": "[pytest] exit 1\nboom"},
        attempt=attempt,
    )


# --- Budgets escalate ---


def test_retry_budget_exhausted_escalates_with_a_readable_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    propose_calls = _wire_mock_pipeline(monkeypatch)
    store = _store(tmp_path)
    job = store.create_job(SCENARIO)

    result = run_job(
        store,
        tmp_path,
        "t",
        job.id,
        verify_fn=lambda root: _failing(),
        judge_fn=_judge(Retryability.RETRYABLE, 0.99),
    )

    assert result.status is JobStatus.WAITING_ON_ESCALATION
    assert result.retry_count == DEFAULT_MAX_RETRIES
    assert len(propose_calls) == DEFAULT_MAX_RETRIES + 1
    (escalation,) = store.list_escalations(job.id)
    assert escalation.reason is EscalationReason.RETRY_BUDGET_EXHAUSTED
    assert escalation.attempt == DEFAULT_MAX_RETRIES + 1
    assert escalation.context["retry_count"] == DEFAULT_MAX_RETRIES
    assert escalation.context["max_retries"] == DEFAULT_MAX_RETRIES
    assert "boom" in str(escalation.context["failure_output"])
    assert escalation.context["judgment"] == {"retryability": "retryable", "confidence": 0.99}


def test_wall_clock_exceeded_after_a_verify_failure_escalates_under_the_retry_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    propose_calls = _wire_mock_pipeline(monkeypatch)
    store = _store(tmp_path)
    job = store.create_job(SCENARIO, budget=Budget(max_retries=5, max_wall_clock_seconds=100.0))
    clock = FakeClock()
    clock.offset = 1000.0

    result = run_job(
        store,
        tmp_path,
        "t",
        job.id,
        verify_fn=lambda root: _failing(),
        judge_fn=_judge(Retryability.RETRYABLE, 0.99),
        clock=clock,
    )

    assert result.status is JobStatus.WAITING_ON_ESCALATION
    assert result.retry_count == 0
    assert len(propose_calls) == 1
    (escalation,) = store.list_escalations(job.id)
    assert escalation.reason is EscalationReason.WALL_CLOCK_EXCEEDED
    assert float(str(escalation.context["elapsed_seconds"])) >= 1000.0


def test_wall_clock_exceeded_on_resume_escalates_before_any_new_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    job = store.create_job(SCENARIO, budget=Budget(max_retries=5, max_wall_clock_seconds=100.0))
    _seed_failed_attempt(store, job, 1)
    store.append_history_event(
        job.id,
        1,
        EventType.JEV_JUDGMENT,
        {"input": {"failure_output": "boom"}, "output": {"error": "x"}, "outcome": "retry"},
    )
    store.increment_retry_count(job.id)
    store.update_job_status(job.id, JobStatus.RETRYING)

    def _fail_if_called(*args: object, **kwargs: object) -> object:
        raise AssertionError("must not start a new attempt with an expired budget")

    monkeypatch.setattr(runner_module, "propose_fix", _fail_if_called)
    clock = FakeClock()
    clock.offset = 1000.0

    result = run_job(store, tmp_path, "t", job.id, judge_fn=_no_judge, clock=clock)

    assert result.status is JobStatus.WAITING_ON_ESCALATION
    (escalation,) = store.list_escalations(job.id)
    assert escalation.reason is EscalationReason.WALL_CLOCK_EXCEEDED
    assert "boom" in str(escalation.context["failure_output"])


def test_budgets_are_per_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    propose_calls = _wire_mock_pipeline(monkeypatch)
    store = _store(tmp_path)
    strict = store.create_job(SCENARIO, budget=Budget(max_retries=0, max_wall_clock_seconds=1e9))

    run_job(
        store,
        tmp_path,
        "t",
        strict.id,
        verify_fn=lambda root: _failing(),
        judge_fn=_judge(Retryability.RETRYABLE, 0.99),
    )
    assert len(propose_calls) == 1
    (escalation,) = store.list_escalations(strict.id)
    assert escalation.reason is EscalationReason.RETRY_BUDGET_EXHAUSTED

    propose_calls.clear()
    default = store.create_job(SCENARIO)
    run_job(
        store,
        tmp_path,
        "t",
        default.id,
        verify_fn=lambda root: _failing(),
        judge_fn=_judge(Retryability.RETRYABLE, 0.99),
    )
    assert len(propose_calls) == DEFAULT_MAX_RETRIES + 1


def test_confident_not_retryable_escalates_and_low_confidence_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    propose_calls = _wire_mock_pipeline(monkeypatch)
    store = _store(tmp_path)

    confident = store.create_job(SCENARIO)
    run_job(
        store,
        tmp_path,
        "t",
        confident.id,
        verify_fn=lambda root: _failing(),
        judge_fn=_judge(Retryability.NOT_RETRYABLE, 0.9),
    )
    assert len(propose_calls) == 1
    (escalation,) = store.list_escalations(confident.id)
    assert escalation.reason is EscalationReason.JEV_NOT_RETRYABLE

    propose_calls.clear()
    unsure = store.create_job(SCENARIO)
    run_job(
        store,
        tmp_path,
        "t",
        unsure.id,
        verify_fn=lambda root: _failing(),
        judge_fn=_judge(Retryability.NOT_RETRYABLE, 0.1),
    )
    assert len(propose_calls) == DEFAULT_MAX_RETRIES + 1


def test_waiting_job_is_not_rerun(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _wire_mock_pipeline(monkeypatch)
    store = _store(tmp_path)
    job = store.create_job(SCENARIO, budget=Budget(max_retries=0, max_wall_clock_seconds=1e9))
    first = run_job(
        store, tmp_path, "t", job.id, verify_fn=lambda root: _failing(), judge_fn=_no_judge
    )
    assert first.status is JobStatus.WAITING_ON_ESCALATION

    def _fail_if_called(*args: object, **kwargs: object) -> object:
        raise AssertionError("an escalated job must not run any step")

    monkeypatch.setattr(runner_module, "propose_fix", _fail_if_called)
    monkeypatch.setattr(runner_module, "apply_fix", _fail_if_called)
    second = run_job(store, tmp_path, "t", job.id, verify_fn=_fail_if_called)  # type: ignore[arg-type]

    assert second.status is JobStatus.WAITING_ON_ESCALATION
    assert len(store.list_escalations(job.id)) == 1


# --- Crash after a failed VERIFY is checkpointed ---


def test_crash_after_failed_verify_does_not_resume_as_succeeded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    propose_calls = _wire_mock_pipeline(monkeypatch)
    store = _store(tmp_path)
    job = store.create_job(SCENARIO)
    _seed_failed_attempt(store, job, 1)
    store.update_job_status(job.id, JobStatus.RUNNING)

    result = run_job(
        store,
        tmp_path,
        "t",
        job.id,
        verify_fn=lambda root: _passing(),
        judge_fn=_judge(Retryability.RETRYABLE, 0.9),
    )

    assert result.status is JobStatus.SUCCEEDED
    assert result.retry_count == 1
    assert propose_calls == [1]  # only attempt 2 proposed; attempt 1 was not re-run
    (judgment,) = _events(store, job.id, EventType.JEV_JUDGMENT)
    assert judgment.attempt == 1
    assert "boom" in str(judgment.payload["input"])


def test_recorded_judgment_is_reused_not_requested_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire_mock_pipeline(monkeypatch)
    store = _store(tmp_path)
    job = store.create_job(SCENARIO)
    _seed_failed_attempt(store, job, 1)
    store.append_history_event(
        job.id,
        1,
        EventType.JEV_JUDGMENT,
        {
            "input": {"failure_output": "boom"},
            "output": {"retryability": "retryable", "confidence": 0.9},
            "outcome": "retry",
        },
    )

    def _fail_if_called(state: dict[str, object]) -> Judgment:
        raise AssertionError("a judgment is already recorded for this attempt")

    result = run_job(
        store,
        tmp_path,
        "t",
        job.id,
        verify_fn=lambda root: _passing(),
        judge_fn=_fail_if_called,
    )

    assert result.status is JobStatus.SUCCEEDED
    assert len(_events(store, job.id, EventType.JEV_JUDGMENT)) == 1


def test_crash_after_failed_verify_at_the_last_retry_escalates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    propose_calls = _wire_mock_pipeline(monkeypatch)
    store = _store(tmp_path)
    job = store.create_job(SCENARIO)
    for attempt in range(1, DEFAULT_MAX_RETRIES + 1):
        _seed_failed_attempt(store, job, attempt)
        store.increment_retry_count(job.id)
    _seed_failed_attempt(store, job, DEFAULT_MAX_RETRIES + 1)
    store.update_job_status(job.id, JobStatus.RUNNING)

    result = run_job(store, tmp_path, "t", job.id, judge_fn=_judge(Retryability.RETRYABLE, 0.9))

    assert result.status is JobStatus.WAITING_ON_ESCALATION
    assert propose_calls == []
    (escalation,) = store.list_escalations(job.id)
    assert escalation.reason is EscalationReason.RETRY_BUDGET_EXHAUSTED


# --- Rollback before retry ---


def _write_target(tmp_path: Path, content: bytes) -> Path:
    path = tmp_path / TARGET_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _file_proposer(
    tmp_path: Path, seen_at_propose: list[bytes]
) -> Callable[[Path, str], FixProposal]:
    def _propose(repo_root: Path, ticket: str) -> FixProposal:
        seen_at_propose.append((tmp_path / TARGET_FILE).read_bytes())
        return FixProposal(
            file_path=TARGET_FILE,
            explanation="e",
            new_content=f"patched-{len(seen_at_propose)}",
        )

    return _propose


def test_retry_sees_the_original_file_and_escalation_leaves_the_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _write_target(tmp_path, ORIGINAL)
    seen: list[bytes] = []
    monkeypatch.setattr(runner_module, "propose_fix", _file_proposer(tmp_path, seen))
    store = _store(tmp_path)
    job = store.create_job(SCENARIO)

    result = run_job(
        store,
        tmp_path,
        "t",
        job.id,
        verify_fn=lambda root: _failing(),
        judge_fn=_judge(Retryability.RETRYABLE, 0.9),
    )

    assert result.status is JobStatus.WAITING_ON_ESCALATION
    # Every attempt investigated the byte-exact original (CRLF included).
    assert seen == [ORIGINAL] * (DEFAULT_MAX_RETRIES + 1)
    # One rollback per retried attempt; none for the escalated final attempt.
    rollbacks = _events(store, job.id, EventType.ROLLBACK)
    assert [e.attempt for e in rollbacks] == list(range(1, DEFAULT_MAX_RETRIES + 1))
    # Escalation keeps the failed attempt's change for a human to review.
    assert b"patched-3" in target.read_bytes()


def test_crash_replay_after_rollback_does_not_duplicate_or_corrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _write_target(tmp_path, ORIGINAL)  # already rolled back before the crash
    seen: list[bytes] = []
    monkeypatch.setattr(runner_module, "propose_fix", _file_proposer(tmp_path, seen))
    store = _store(tmp_path)
    job = store.create_job(SCENARIO)
    _seed_failed_attempt(store, job, 1, previous_content=ORIGINAL.decode("utf-8"))
    store.append_history_event(
        job.id,
        1,
        EventType.JEV_JUDGMENT,
        {
            "input": {"failure_output": "boom"},
            "output": {"retryability": "retryable", "confidence": 0.9},
            "outcome": "retry",
        },
    )
    store.append_history_event(job.id, 1, EventType.ROLLBACK, {"file_path": TARGET_FILE})

    result = run_job(
        store,
        tmp_path,
        "t",
        job.id,
        verify_fn=lambda root: _passing(),
        judge_fn=_no_judge,
    )

    assert result.status is JobStatus.SUCCEEDED
    assert seen == [ORIGINAL]
    assert len(_events(store, job.id, EventType.ROLLBACK)) == 1
    assert target.read_bytes() == b"patched-1"


def test_mid_apply_crash_restores_the_true_original_not_the_applied_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The crash happened after apply_fix wrote the change but before the APPLY
    # `after` checkpoint: the file already holds the new content, yet the saved
    # `before` state still has the true original.
    target = _write_target(tmp_path, b"NEW")
    seen: list[bytes] = []
    monkeypatch.setattr(runner_module, "propose_fix", _file_proposer(tmp_path, seen))
    store = _store(tmp_path)
    job = store.create_job(SCENARIO, budget=Budget(max_retries=1, max_wall_clock_seconds=1e9))
    state: dict[str, object] = {
        "file_path": TARGET_FILE,
        "explanation": "e",
        "new_content": "NEW",
    }
    store.add_checkpoint(job.id, StepName.PROPOSE, CheckpointPhase.BEFORE, attempt=1)
    store.add_checkpoint(job.id, StepName.PROPOSE, CheckpointPhase.AFTER, state, attempt=1)
    store.add_checkpoint(
        job.id,
        StepName.APPLY,
        CheckpointPhase.BEFORE,
        {"file_path": TARGET_FILE, "previous_content": ORIGINAL.decode("utf-8")},
        attempt=1,
    )
    store.update_job_status(job.id, JobStatus.RUNNING)

    result = run_job(
        store,
        tmp_path,
        "t",
        job.id,
        verify_fn=lambda root: _failing(),
        judge_fn=_judge(Retryability.RETRYABLE, 0.9),
    )

    assert result.status is JobStatus.WAITING_ON_ESCALATION
    assert seen == [ORIGINAL]  # attempt 2 saw the true original, not "NEW"
    assert target.read_bytes() == b"patched-1"  # attempt 2's own (first fresh) proposal


# --- Steps still fail; history is complete ---


def test_step_exceptions_still_end_failed_not_escalated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(repo_root: Path, ticket: str) -> FixProposal:
        raise RuntimeError("propose blew up")

    monkeypatch.setattr(runner_module, "propose_fix", _boom)
    store = _store(tmp_path)
    job = store.create_job(SCENARIO)

    result = run_job(store, tmp_path, "t", job.id, judge_fn=_no_judge)

    assert result.status is JobStatus.FAILED
    assert store.list_escalations(job.id) == []
    assert len(_events(store, job.id, EventType.STEP_ERROR)) == 1


def test_history_alone_reconstructs_the_jobs_timeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _write_target(tmp_path, ORIGINAL)
    monkeypatch.setattr(runner_module, "propose_fix", _file_proposer(tmp_path, []))
    store = _store(tmp_path)
    job = store.create_job(SCENARIO, budget=Budget(max_retries=1, max_wall_clock_seconds=1e9))

    result = run_job(
        store,
        tmp_path,
        "t",
        job.id,
        verify_fn=lambda root: _failing(),
        judge_fn=_judge(Retryability.RETRYABLE, 0.9),
    )
    assert target.exists()

    history = store.list_history(job.id)
    assert [e.event_type for e in history] == [
        EventType.STATUS_TRANSITION,  # pending -> running (attempt 1)
        EventType.JEV_JUDGMENT,  # attempt 1 verify failure judged
        EventType.ROLLBACK,
        EventType.RETRY,
        EventType.STATUS_TRANSITION,  # running -> retrying
        EventType.STATUS_TRANSITION,  # retrying -> running (attempt 2)
        EventType.JEV_JUDGMENT,  # attempt 2 verify failure judged
        EventType.STATUS_TRANSITION,  # running -> waiting_on_escalation
        EventType.ESCALATION,
    ]

    # Every status change has an event, and the chain of transitions is
    # unbroken from `pending` to the job's actual final status.
    transitions = [e.payload for e in history if e.event_type is EventType.STATUS_TRANSITION]
    assert transitions[0]["from"] == JobStatus.PENDING.value
    for previous, current in zip(transitions, transitions[1:], strict=False):
        assert current["from"] == previous["to"]
    assert transitions[-1]["to"] == result.status.value
    assert [e.id for e in history] == sorted(e.id for e in history)
