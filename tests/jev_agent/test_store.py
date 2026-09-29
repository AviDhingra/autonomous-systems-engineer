from pathlib import Path

import pytest

from jev_agent.models import (
    CheckpointPhase,
    EscalationReason,
    EventType,
    JobStatus,
    ResolutionState,
    StepName,
)
from jev_agent.store import JobStore


def _store(tmp_path: Path) -> JobStore:
    return JobStore(f"sqlite:///{tmp_path / 'jev_agent_test.db'}")


def test_create_job_starts_pending(tmp_path: Path) -> None:
    store = _store(tmp_path)

    job = store.create_job("S02-unsupported-patch-fields")

    assert job.status is JobStatus.PENDING
    assert job.scenario == "S02-unsupported-patch-fields"
    assert job.retry_count == 0

    reloaded = store.get_job(job.id)
    assert reloaded is not None
    assert reloaded.id == job.id
    assert reloaded.scenario == job.scenario
    assert reloaded.status == job.status
    assert reloaded.retry_count == 0


def test_get_job_returns_none_for_missing_id(tmp_path: Path) -> None:
    store = _store(tmp_path)

    assert store.get_job("missing") is None


def test_update_job_status_persists(tmp_path: Path) -> None:
    store = _store(tmp_path)
    job = store.create_job("S02-unsupported-patch-fields")

    updated = store.update_job_status(job.id, JobStatus.RUNNING)

    assert updated.status is JobStatus.RUNNING
    assert store.get_job(job.id).status is JobStatus.RUNNING  # type: ignore[union-attr]


def test_add_and_list_checkpoints_in_order(tmp_path: Path) -> None:
    store = _store(tmp_path)
    job = store.create_job("S02-unsupported-patch-fields")

    store.add_checkpoint(job.id, StepName.PROPOSE, CheckpointPhase.BEFORE)
    store.add_checkpoint(
        job.id, StepName.PROPOSE, CheckpointPhase.AFTER, {"file_path": "a.py"}
    )
    store.add_checkpoint(job.id, StepName.APPLY, CheckpointPhase.BEFORE)

    checkpoints = store.list_checkpoints(job.id)

    assert [(c.step, c.phase) for c in checkpoints] == [
        (StepName.PROPOSE, CheckpointPhase.BEFORE),
        (StepName.PROPOSE, CheckpointPhase.AFTER),
        (StepName.APPLY, CheckpointPhase.BEFORE),
    ]
    assert checkpoints[1].state == {"file_path": "a.py"}
    assert all(c.attempt == 1 for c in checkpoints)


def test_add_checkpoint_records_attempt(tmp_path: Path) -> None:
    store = _store(tmp_path)
    job = store.create_job("S02-unsupported-patch-fields")

    store.add_checkpoint(job.id, StepName.PROPOSE, CheckpointPhase.BEFORE, attempt=2)
    checkpoints = store.list_checkpoints(job.id)

    assert checkpoints[0].attempt == 2


def test_increment_retry_count(tmp_path: Path) -> None:
    store = _store(tmp_path)
    job = store.create_job("S02-unsupported-patch-fields")

    once = store.increment_retry_count(job.id)
    assert once.retry_count == 1

    twice = store.increment_retry_count(job.id)
    assert twice.retry_count == 2

    assert store.get_job(job.id).retry_count == 2  # type: ignore[union-attr]


def test_find_active_job_skips_terminal_jobs(tmp_path: Path) -> None:
    store = _store(tmp_path)
    finished = store.create_job("S02-unsupported-patch-fields")
    store.update_job_status(finished.id, JobStatus.SUCCEEDED)

    assert store.find_active_job("S02-unsupported-patch-fields") is None

    active = store.create_job("S02-unsupported-patch-fields")
    store.update_job_status(active.id, JobStatus.RUNNING)

    found = store.find_active_job("S02-unsupported-patch-fields")
    assert found is not None
    assert found.id == active.id


def test_find_active_job_returns_none_for_unknown_scenario(tmp_path: Path) -> None:
    store = _store(tmp_path)

    assert store.find_active_job("no-such-scenario") is None


# --- Milestone 3: execution_history ---


def test_history_round_trips_payload_in_insertion_order(tmp_path: Path) -> None:
    store = JobStore(f"sqlite:///{tmp_path / 'history_test.db'}")
    job = store.create_job("S02-unsupported-patch-fields")

    first = store.append_history_event(
        job.id, 1, EventType.JEV_JUDGMENT, {"n": 1, "nested": {"a": [1]}}
    )
    second = store.append_history_event(job.id, 2, EventType.JEV_JUDGMENT, {"n": 2})

    events = store.list_history(job.id)
    assert [e.id for e in events] == [first.id, second.id]
    assert events[0].payload == {"n": 1, "nested": {"a": [1]}}
    assert [e.attempt for e in events] == [1, 2]
    assert all(e.event_type is EventType.JEV_JUDGMENT for e in events)


def test_history_is_scoped_per_job(tmp_path: Path) -> None:
    store = JobStore(f"sqlite:///{tmp_path / 'history_scope_test.db'}")
    a = store.create_job("S02-unsupported-patch-fields")
    b = store.create_job("S02-unsupported-patch-fields")

    store.append_history_event(a.id, 1, EventType.JEV_JUDGMENT, {"job": "a"})

    assert store.list_history(b.id) == []
    assert [e.payload for e in store.list_history(a.id)] == [{"job": "a"}]


# --- Milestone 4: budgets, atomic transitions, escalations ---


def test_budget_round_trips_and_defaults(tmp_path: Path) -> None:
    from jev_agent.models import DEFAULT_BUDGET, Budget

    store = JobStore(f"sqlite:///{tmp_path / 'budget_test.db'}")
    custom = Budget(max_retries=5, max_wall_clock_seconds=42.5)

    assert store.create_job("S02").budget == DEFAULT_BUDGET
    job = store.create_job("S02", budget=custom)
    fetched = store.get_job(job.id)
    assert fetched is not None and fetched.budget == custom


def test_transition_updates_status_and_records_one_event(tmp_path: Path) -> None:
    store = JobStore(f"sqlite:///{tmp_path / 'transition_test.db'}")
    job = store.create_job("S02")

    updated = store.transition(job.id, JobStatus.RUNNING, 1, "attempt started")

    assert updated.status is JobStatus.RUNNING
    (event,) = store.list_history(job.id)
    assert event.event_type is EventType.STATUS_TRANSITION
    assert event.payload == {"from": "pending", "to": "running", "reason": "attempt started"}


def test_transition_to_the_same_status_is_a_no_op(tmp_path: Path) -> None:
    store = JobStore(f"sqlite:///{tmp_path / 'noop_test.db'}")
    job = store.create_job("S02")
    store.transition(job.id, JobStatus.RUNNING, 1, "attempt started")

    store.transition(job.id, JobStatus.RUNNING, 1, "attempt started again")

    assert len(store.list_history(job.id)) == 1


def test_transition_and_its_event_are_atomic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from jev_agent import store as store_module

    store = JobStore(f"sqlite:///{tmp_path / 'atomic_test.db'}")
    job = store.create_job("S02")

    def _boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("history write failed")

    monkeypatch.setattr(store_module, "_history_row", _boom)
    with pytest.raises(RuntimeError):
        store.transition(job.id, JobStatus.RUNNING, 1, "attempt started")

    fetched = store.get_job(job.id)
    assert fetched is not None and fetched.status is JobStatus.PENDING


def test_increment_retry_count_records_a_retry_event(tmp_path: Path) -> None:
    store = JobStore(f"sqlite:///{tmp_path / 'retry_event_test.db'}")
    job = store.create_job("S02")

    updated = store.increment_retry_count(job.id, reason="verify failed")

    assert updated.retry_count == 1
    (event,) = store.list_history(job.id)
    assert event.event_type is EventType.RETRY
    assert event.attempt == 1
    assert event.payload["to_attempt"] == 2


def test_escalate_writes_record_status_and_events_together(tmp_path: Path) -> None:
    store = JobStore(f"sqlite:///{tmp_path / 'escalate_test.db'}")
    job = store.create_job("S02")

    escalation = store.escalate(
        job.id, 2, EscalationReason.WALL_CLOCK_EXCEEDED, {"elapsed_seconds": 9.0}
    )

    assert escalation.reason is EscalationReason.WALL_CLOCK_EXCEEDED
    assert escalation.resolution_state is ResolutionState.PENDING
    assert escalation.resolved_at is None
    assert escalation.context == {"elapsed_seconds": 9.0}
    assert store.list_escalations(job.id) == [escalation]
    fetched = store.get_job(job.id)
    assert fetched is not None and fetched.status is JobStatus.WAITING_ON_ESCALATION
    types = [e.event_type for e in store.list_history(job.id)]
    assert types == [EventType.STATUS_TRANSITION, EventType.ESCALATION]


def test_escalate_is_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from jev_agent import store as store_module

    store = JobStore(f"sqlite:///{tmp_path / 'escalate_atomic_test.db'}")
    job = store.create_job("S02")

    def _boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("history write failed")

    monkeypatch.setattr(store_module, "_history_row", _boom)
    with pytest.raises(RuntimeError):
        store.escalate(job.id, 1, EscalationReason.RETRY_BUDGET_EXHAUSTED, {})

    fetched = store.get_job(job.id)
    assert fetched is not None and fetched.status is JobStatus.PENDING
    assert store.list_escalations(job.id) == []


def test_find_active_job_ignores_jobs_waiting_on_escalation(tmp_path: Path) -> None:
    store = JobStore(f"sqlite:///{tmp_path / 'waiting_test.db'}")
    job = store.create_job("S02")
    store.escalate(job.id, 1, EscalationReason.JEV_NOT_RETRYABLE, {})

    assert store.find_active_job("S02") is None


def test_append_history_event_once_skips_a_duplicate_per_attempt(tmp_path: Path) -> None:
    store = JobStore(f"sqlite:///{tmp_path / 'once_test.db'}")
    job = store.create_job("S02")

    first = store.append_history_event_once(job.id, 1, EventType.ROLLBACK, {"n": 1})
    duplicate = store.append_history_event_once(job.id, 1, EventType.ROLLBACK, {"n": 2})
    other_attempt = store.append_history_event_once(job.id, 2, EventType.ROLLBACK, {"n": 3})

    assert first is not None and duplicate is None and other_attempt is not None
    assert len(store.list_history(job.id)) == 2


def test_outdated_schema_fails_with_a_clear_message(tmp_path: Path) -> None:
    import sqlite3

    db_path = tmp_path / "old_schema.db"
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE jobs (id VARCHAR(36) PRIMARY KEY, scenario VARCHAR(200))")
    connection.commit()
    connection.close()

    with pytest.raises(RuntimeError, match=r"outdated schema.*'jobs'.*max_retries"):
        JobStore(f"sqlite:///{db_path}")
