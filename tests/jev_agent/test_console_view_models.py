from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jev_agent.console.app import create_app
from jev_agent.console.view_models import (
    STATUS_BADGES,
    STATUS_LABELS,
    budget_summary,
    elapsed_seconds,
    group_by_attempt,
    humanize_duration,
    is_active,
    judgment_summary,
    status_badge,
)
from jev_agent.models import (
    Budget,
    Checkpoint,
    CheckpointPhase,
    EventType,
    HistoryEvent,
    Job,
    JobStatus,
    StepName,
)

T0 = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
BUDGET = Budget(max_retries=2, max_wall_clock_seconds=600.0)


def _job(
    status: JobStatus = JobStatus.RUNNING,
    retry_count: int = 0,
    updated_after: float = 0.0,
) -> Job:
    return Job(
        id="j",
        scenario="S",
        status=status,
        created_at=T0,
        updated_at=T0 + timedelta(seconds=updated_after),
        retry_count=retry_count,
        budget=BUDGET,
    )


def _checkpoint(attempt: int, step: StepName = StepName.PROPOSE) -> Checkpoint:
    return Checkpoint(
        id=attempt, job_id="j", step=step, phase=CheckpointPhase.AFTER, attempt=attempt
    )


def _event(attempt: int, event_type: EventType, payload: dict[str, object]) -> HistoryEvent:
    return HistoryEvent(
        id=attempt, job_id="j", attempt=attempt, event_type=event_type, payload=payload
    )


def test_every_status_has_badge_and_label() -> None:
    assert set(STATUS_BADGES) == set(JobStatus)
    assert set(STATUS_LABELS) == set(JobStatus)
    assert len({status_badge(status) for status in JobStatus}) == len(JobStatus)


def test_only_unfinished_statuses_are_active() -> None:
    active = {status for status in JobStatus if is_active(status)}

    assert active == {JobStatus.PENDING, JobStatus.RUNNING, JobStatus.RETRYING}


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0, "0s"), (59.9, "59s"), (60, "1m 0s"), (125, "2m 5s"), (3660, "1h 1m"), (-5, "0s")],
)
def test_humanize_duration(seconds: float, expected: str) -> None:
    assert humanize_duration(seconds) == expected


def test_elapsed_runs_to_now_while_active() -> None:
    job = _job(JobStatus.RUNNING, updated_after=10)

    assert elapsed_seconds(job, T0 + timedelta(seconds=90)) == 90


def test_elapsed_stops_at_last_update_when_finished() -> None:
    for status in (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.WAITING_ON_ESCALATION):
        job = _job(status, updated_after=45)

        assert elapsed_seconds(job, T0 + timedelta(hours=5)) == 45


def test_elapsed_handles_naive_datetimes_from_sqlite() -> None:
    job = Job(
        id="j",
        scenario="S",
        status=JobStatus.SUCCEEDED,
        created_at=T0.replace(tzinfo=None),
        updated_at=(T0 + timedelta(seconds=30)).replace(tzinfo=None),
    )

    assert elapsed_seconds(job, T0) == 30


def test_budget_summary_flags_exhaustion() -> None:
    job = _job(JobStatus.WAITING_ON_ESCALATION, retry_count=2, updated_after=700)

    summary = budget_summary(job, T0 + timedelta(hours=1))

    assert (summary.retries_used, summary.max_retries) == (2, 2)
    assert summary.retries_exhausted
    assert summary.wall_clock_exceeded
    assert summary.elapsed_label == "11m 40s"
    assert summary.max_wall_clock_label == "10m 0s"


def test_budget_summary_under_budget() -> None:
    summary = budget_summary(_job(retry_count=1), T0 + timedelta(seconds=5))

    assert not summary.retries_exhausted
    assert not summary.wall_clock_exceeded


def test_judgment_summary_reads_output_and_outcome() -> None:
    event = _event(
        1,
        EventType.JEV_JUDGMENT,
        {
            "input": {},
            "output": {"retryability": "not_retryable", "confidence": 0.9},
            "outcome": "escalate",
        },
    )

    summary = judgment_summary(event)

    assert summary is not None
    assert summary.retryability == "not_retryable"
    assert summary.confidence_label == "90%"
    assert summary.outcome == "escalate"


def test_judgment_summary_none_without_output_or_wrong_type() -> None:
    failed = _event(1, EventType.JEV_JUDGMENT, {"input": {}, "output": None, "outcome": "retry"})
    other = _event(1, EventType.RETRY, {})

    assert judgment_summary(failed) is None
    assert judgment_summary(other) is None


def test_group_by_attempt_orders_and_keeps_chronology() -> None:
    checkpoints = [_checkpoint(1), _checkpoint(2), _checkpoint(1, StepName.VERIFY)]
    events = [
        _event(2, EventType.RETRY, {}),
        _event(1, EventType.ROLLBACK, {}),
        _event(3, EventType.ESCALATION, {}),
    ]

    attempts = group_by_attempt(checkpoints, events)

    assert [a.attempt for a in attempts] == [1, 2, 3]
    assert [c.step for c in attempts[0].checkpoints] == [StepName.PROPOSE, StepName.VERIFY]
    assert attempts[2].checkpoints == []
    assert [e.event_type for e in attempts[2].events] == [EventType.ESCALATION]


def test_group_by_attempt_empty() -> None:
    assert group_by_attempt([], []) == []


def test_create_app_wires_store_templates_and_static(tmp_path: Path) -> None:
    app = create_app(f"sqlite:///{tmp_path / 'console_test.db'}")

    assert app.state.store.list_jobs() == []
    assert app.state.templates is not None
    assert TestClient(app).get("/static/console.css").status_code == 200
