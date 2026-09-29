"""Group 4: live-refresh scoping, every event type rendering, and the display
view models (steps, events, escalations)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jev_agent.console.app import create_app
from jev_agent.console.view_models import (
    display_attempts,
    escalation_view,
    event_view,
    step_views,
)
from jev_agent.models import (
    Checkpoint,
    CheckpointPhase,
    Escalation,
    EscalationReason,
    EventType,
    HistoryEvent,
    JobStatus,
    StepName,
)
from jev_agent.store import JobStore

T0 = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    return JobStore(f"sqlite:///{tmp_path / 'render_test.db'}")


@pytest.fixture
def client(tmp_path: Path, store: JobStore) -> TestClient:
    return TestClient(create_app(f"sqlite:///{tmp_path / 'render_test.db'}"))


def _poll_marker(job_id: str, fragment: str) -> str:
    return f'hx-get="/jobs/{job_id}/{fragment}"'


@pytest.mark.parametrize("status", [JobStatus.RUNNING, JobStatus.RETRYING, JobStatus.PENDING])
def test_active_job_page_polls(client: TestClient, store: JobStore, status: JobStatus) -> None:
    job = store.create_job("S-active")
    store.update_job_status(job.id, status)

    page = client.get(f"/jobs/{job.id}").text

    assert _poll_marker(job.id, "status") in page
    assert _poll_marker(job.id, "history") in page
    assert _poll_marker(job.id, "status") in client.get(f"/jobs/{job.id}/status").text
    assert _poll_marker(job.id, "history") in client.get(f"/jobs/{job.id}/history").text


@pytest.mark.parametrize(
    "status", [JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.WAITING_ON_ESCALATION]
)
def test_finished_job_page_does_not_poll(
    client: TestClient, store: JobStore, status: JobStatus
) -> None:
    job = store.create_job("S-done")
    store.update_job_status(job.id, status)

    for path in (f"/jobs/{job.id}", f"/jobs/{job.id}/status", f"/jobs/{job.id}/history"):
        assert "hx-get" not in client.get(path).text


def test_every_event_type_renders(client: TestClient, store: JobStore) -> None:
    job = store.create_job("S-all-events")
    store.transition(job.id, JobStatus.RUNNING, 1, "attempt started")
    store.increment_retry_count(job.id, reason="verify failed")
    store.append_history_event(job.id, 1, EventType.ROLLBACK, {"file_path": "a.py"})
    store.append_history_event(
        job.id,
        1,
        EventType.JEV_JUDGMENT,
        {
            "input": {},
            "output": {"retryability": "not_retryable", "confidence": 0.9},
            "outcome": "escalate",
        },
    )
    store.append_history_event(
        job.id, 1, EventType.JEV_JUDGMENT, {"input": {}, "output": None, "outcome": "retry"}
    )
    store.append_history_event(
        job.id, 1, EventType.STEP_ERROR, {"step": "propose", "error_type": "E", "message": "m"}
    )
    escalation = store.escalate(
        job.id,
        1,
        EscalationReason.JEV_NOT_RETRYABLE,
        {
            "retry_count": 1,
            "max_retries": 2,
            "elapsed_seconds": 5.0,
            "max_wall_clock_seconds": 60.0,
            "judgment": {"retryability": "not_retryable", "confidence": 0.9},
            "failure_output": "x",
        },
    )
    store.resolve_escalation(escalation.id, "done")

    response = client.get(f"/jobs/{job.id}")

    assert response.status_code == 200
    for expected in (
        "Status: pending → running",
        "Retry: attempt",
        "Rolled back",
        "JEV judged the failure not retryable",
        "confidence 90%",
        "JEV judgment unavailable",
        "Propose step raised an error",
        "Escalated: jev_not_retryable",
        "Escalation #",
        "not retryable (90% confidence)",
    ):
        assert expected in response.text, expected


def _cp(
    step: StepName, phase: CheckpointPhase, state: dict[str, object] | None = None
) -> Checkpoint:
    return Checkpoint(id=1, job_id="j", step=step, phase=phase, state=state or {})


def _event(event_type: EventType, payload: dict[str, object]) -> HistoryEvent:
    return HistoryEvent(id=1, job_id="j", attempt=1, event_type=event_type, payload=payload)


def test_step_views_reflect_outcomes() -> None:
    views = step_views(
        [
            _cp(StepName.PROPOSE, CheckpointPhase.BEFORE),
            _cp(StepName.PROPOSE, CheckpointPhase.AFTER, {"file_path": "a.py"}),
            _cp(StepName.APPLY, CheckpointPhase.BEFORE),
            _cp(StepName.APPLY, CheckpointPhase.AFTER, {"file_path": "a.py"}),
            _cp(StepName.VERIFY, CheckpointPhase.BEFORE),
            _cp(
                StepName.VERIFY,
                CheckpointPhase.AFTER,
                {"passed": False, "checks": [{"name": "pytest", "passed": False}]},
            ),
        ]
    )

    assert [(v.name, v.state) for v in views] == [
        ("propose", "done"),
        ("apply", "done"),
        ("verify", "failed"),
    ]
    assert views[0].detail == "a.py"
    assert "pytest" in views[2].detail


def test_step_views_started_without_after_and_skips_unreached() -> None:
    views = step_views(
        [
            _cp(StepName.PROPOSE, CheckpointPhase.BEFORE),
            _cp(StepName.PROPOSE, CheckpointPhase.AFTER, {"file_path": "a.py"}),
            _cp(StepName.APPLY, CheckpointPhase.BEFORE),
        ]
    )

    assert [(v.name, v.state) for v in views] == [("propose", "done"), ("apply", "started")]


def test_step_views_passing_verify() -> None:
    views = step_views(
        [_cp(StepName.VERIFY, CheckpointPhase.AFTER, {"passed": True, "checks": []})]
    )

    assert (views[0].state, views[0].detail) == ("done", "passed")


def test_event_view_has_title_for_every_event_type() -> None:
    cases: dict[EventType, dict[str, object]] = {
        EventType.STATUS_TRANSITION: {"from": "pending", "to": "running", "reason": "go"},
        EventType.RETRY: {"from_attempt": 1, "to_attempt": 2, "reason": "r"},
        EventType.ROLLBACK: {"file_path": "a.py"},
        EventType.STEP_ERROR: {"step": "verify", "error_type": "E", "message": "m"},
        EventType.ESCALATION_RESOLVED: {"escalation_id": 3, "note": ""},
        EventType.ESCALATION: {"reason": "retry_budget_exhausted", "context": {}},
        EventType.JEV_JUDGMENT: {"input": {}, "output": None, "outcome": "retry"},
    }
    assert set(cases) == set(EventType)

    for event_type, payload in cases.items():
        view = event_view(_event(event_type, payload))
        assert view.title
        assert view.kind == event_type.value


def test_event_view_judgment_carries_summary() -> None:
    view = event_view(
        _event(
            EventType.JEV_JUDGMENT,
            {"output": {"retryability": "retryable", "confidence": 0.75}, "outcome": "retry"},
        )
    )

    assert view.judgment is not None
    assert view.title == "JEV judged the failure retryable"
    assert "confidence 75%" in view.details


def test_display_attempts_combines_steps_and_events() -> None:
    attempts = display_attempts(
        [_cp(StepName.PROPOSE, CheckpointPhase.BEFORE)],
        [_event(EventType.ROLLBACK, {"file_path": "a.py"})],
    )

    assert len(attempts) == 1
    assert attempts[0].steps[0].state == "started"
    assert attempts[0].events[0].kind == "rollback"


def test_escalation_view_readable_facts() -> None:
    escalation = Escalation(
        id=4,
        job_id="j",
        attempt=2,
        reason=EscalationReason.WALL_CLOCK_EXCEEDED,
        context={
            "retry_count": 1,
            "max_retries": 3,
            "elapsed_seconds": 700.0,
            "max_wall_clock_seconds": 600.0,
            "judgment": None,
            "failure_output": "boom",
        },
        created_at=T0,
    )

    view = escalation_view(escalation)

    assert view.reason_label == "Wall-clock budget exceeded"
    assert view.retries == "1 of 3"
    assert view.elapsed == "11m 40s of 10m 0s"
    assert view.judgment == "none consulted"
    assert view.failure_output == "boom"
    assert not view.resolved
