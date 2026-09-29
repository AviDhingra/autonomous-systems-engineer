from pathlib import Path

from jev_agent.models import CheckpointPhase, EventType, JobStatus, StepName
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
