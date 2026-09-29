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


def _escalated(store: JobStore, scenario: str = "S02-unsupported-patch-fields"):  # type: ignore[no-untyped-def]
    job = store.create_job(scenario)
    escalation = store.escalate(job.id, 2, EscalationReason.RETRY_BUDGET_EXHAUSTED, {"k": 1})
    return job, escalation


def test_list_jobs_newest_first(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = store.create_job("a")
    second = store.create_job("b")

    assert [job.id for job in store.list_jobs()] == [second.id, first.id]


def test_simulation_marker_round_trips(tmp_path: Path) -> None:
    store = _store(tmp_path)
    real = store.create_job("S")
    simulated = store.create_job("S", simulation="retry-then-pass")

    assert real.simulation is None
    assert simulated.simulation == "retry-then-pass"
    assert store.get_job(real.id).simulation is None  # type: ignore[union-attr]
    assert store.get_job(simulated.id).simulation == "retry-then-pass"  # type: ignore[union-attr]
    # A status change must not drop the marker.
    store.transition(simulated.id, JobStatus.RUNNING, 1, "attempt started")
    assert store.get_job(simulated.id).simulation == "retry-then-pass"  # type: ignore[union-attr]


def _filter_fixture(store: JobStore) -> dict[str, str]:
    real = store.create_job("S")
    happy = store.create_job("S", simulation="happy-path")
    budget = store.create_job("S", simulation="retry-budget")
    store.update_job_status(budget.id, JobStatus.WAITING_ON_ESCALATION)
    return {"real": real.id, "happy": happy.id, "budget": budget.id}


def test_list_jobs_filters_by_status(tmp_path: Path) -> None:
    store = _store(tmp_path)
    ids = _filter_fixture(store)

    waiting = store.list_jobs(status=JobStatus.WAITING_ON_ESCALATION)
    pending = store.list_jobs(status=JobStatus.PENDING)

    assert [job.id for job in waiting] == [ids["budget"]]
    assert {job.id for job in pending} == {ids["real"], ids["happy"]}


def test_list_jobs_filters_simulated_or_real(tmp_path: Path) -> None:
    store = _store(tmp_path)
    ids = _filter_fixture(store)

    assert {job.id for job in store.list_jobs(simulated=True)} == {ids["happy"], ids["budget"]}
    assert [job.id for job in store.list_jobs(simulated=False)] == [ids["real"]]
    assert len(store.list_jobs(simulated=None)) == 3


def test_list_jobs_filters_by_story(tmp_path: Path) -> None:
    store = _store(tmp_path)
    ids = _filter_fixture(store)

    assert [job.id for job in store.list_jobs(story="happy-path")] == [ids["happy"]]
    assert store.list_jobs(story="no-such-story") == []


def test_list_jobs_filters_by_id_prefix(tmp_path: Path) -> None:
    store = _store(tmp_path)
    ids = _filter_fixture(store)

    assert [job.id for job in store.list_jobs(id_prefix=ids["happy"][:8])] == [ids["happy"]]
    assert len(store.list_jobs(id_prefix="")) == 3
    # LIKE wildcards in user input are literal, not patterns.
    assert store.list_jobs(id_prefix="%") == []
    assert store.list_jobs(id_prefix="_") == []


def test_list_jobs_filters_combine(tmp_path: Path) -> None:
    store = _store(tmp_path)
    ids = _filter_fixture(store)

    combined = store.list_jobs(status=JobStatus.PENDING, simulated=True)

    assert [job.id for job in combined] == [ids["happy"]]


def test_list_pending_escalations_excludes_resolved(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _, first = _escalated(store, "a")
    _, second = _escalated(store, "b")

    store.resolve_escalation(first.id)

    assert [e.id for e in store.list_pending_escalations()] == [second.id]


def test_resolve_escalation_records_row_and_event(tmp_path: Path) -> None:
    store = _store(tmp_path)
    job, escalation = _escalated(store)

    resolved = store.resolve_escalation(escalation.id, "looked at it")

    assert resolved.resolution_state is ResolutionState.RESOLVED
    assert resolved.resolved_at is not None
    assert resolved.resolution_note == "looked at it"
    reloaded = store.get_escalation(escalation.id)
    assert reloaded is not None
    assert reloaded.resolution_state is ResolutionState.RESOLVED
    assert reloaded.resolved_at is not None
    assert reloaded.resolution_note == "looked at it"
    events = [
        e for e in store.list_history(job.id) if e.event_type is EventType.ESCALATION_RESOLVED
    ]
    assert len(events) == 1
    assert events[0].payload == {"escalation_id": escalation.id, "note": "looked at it"}


def test_resolve_escalation_leaves_job_status(tmp_path: Path) -> None:
    store = _store(tmp_path)
    job, escalation = _escalated(store)

    store.resolve_escalation(escalation.id)

    assert store.get_job(job.id).status is JobStatus.WAITING_ON_ESCALATION  # type: ignore[union-attr]


def test_resolve_escalation_twice_adds_one_event(tmp_path: Path) -> None:
    store = _store(tmp_path)
    job, escalation = _escalated(store)

    store.resolve_escalation(escalation.id, "first")
    again = store.resolve_escalation(escalation.id, "second")

    assert again.resolution_note == "first"
    resolved_events = [
        e for e in store.list_history(job.id) if e.event_type is EventType.ESCALATION_RESOLVED
    ]
    assert len(resolved_events) == 1


def test_resolve_unknown_escalation_raises(tmp_path: Path) -> None:
    store = _store(tmp_path)

    with pytest.raises(KeyError):
        store.resolve_escalation(999)
    assert store.get_escalation(999) is None
