from pathlib import Path

from jev_agent.history_format import format_escalation, format_event, format_history
from jev_agent.models import EscalationReason, EventType, JobStatus
from jev_agent.store import JobStore


def test_every_event_type_renders_one_line(tmp_path: Path) -> None:
    store = JobStore(f"sqlite:///{tmp_path / 'format_test.db'}")
    job = store.create_job("S02")
    store.append_history_event(
        job.id,
        1,
        EventType.JEV_JUDGMENT,
        {
            "input": {},
            "output": {"retryability": "retryable", "confidence": 0.9},
            "outcome": "retry",
        },
    )
    store.append_history_event(
        job.id, 1, EventType.STEP_ERROR, {"step": "propose", "error_type": "E", "message": "m"}
    )
    store.append_history_event(job.id, 1, EventType.ROLLBACK, {"file_path": "f.py"})
    store.transition(job.id, JobStatus.RUNNING, 1, "attempt started")
    store.increment_retry_count(job.id, reason="why")
    escalation = store.escalate(job.id, 2, EscalationReason.RETRY_BUDGET_EXHAUSTED, _context())
    store.resolve_escalation(escalation.id)

    events = store.list_history(job.id)
    assert {e.event_type for e in events} == set(EventType)
    lines = [format_event(e) for e in events]
    assert all(line.startswith("- attempt ") and "\n" not in line for line in lines)
    assert format_history(events).count("\n") == len(events) - 1


def test_escalation_summary_shows_reason_and_usage(tmp_path: Path) -> None:
    store = JobStore(f"sqlite:///{tmp_path / 'format_escalation_test.db'}")
    job = store.create_job("S02")
    escalation = store.escalate(job.id, 3, EscalationReason.WALL_CLOCK_EXCEEDED, _context())

    text = format_escalation(escalation)

    assert "wall_clock_exceeded" in text
    assert "retries: 1 of 2" in text
    assert "elapsed: 12.5s of 10.0s" in text


def _context() -> dict[str, object]:
    return {
        "retry_count": 1,
        "max_retries": 2,
        "elapsed_seconds": 12.5,
        "max_wall_clock_seconds": 10.0,
        "judgment": None,
        "failure_output": "boom",
    }


def test_format_event_escalation_resolved(tmp_path: Path) -> None:
    store = JobStore(f"sqlite:///{tmp_path / 'format_resolved_test.db'}")
    job = store.create_job("S02-unsupported-patch-fields")
    escalation = store.escalate(job.id, 1, EscalationReason.RETRY_BUDGET_EXHAUSTED, _context())
    store.resolve_escalation(escalation.id, "checked")

    event = store.list_history(job.id)[-1]

    assert event.event_type is EventType.ESCALATION_RESOLVED
    assert format_event(event) == (
        f"- attempt 1 escalation_resolved: escalation {escalation.id} resolved (checked)"
    )
