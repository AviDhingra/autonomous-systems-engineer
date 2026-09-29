"""Pure functions turning store records into display-ready values.

No HTTP, no templates, no store access: everything here is unit-testable with
plain dataclasses."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime

from jev_agent.models import (
    Checkpoint,
    EventType,
    HistoryEvent,
    Job,
    JobStatus,
)

ACTIVE_JOB_STATUSES = frozenset({JobStatus.PENDING, JobStatus.RUNNING, JobStatus.RETRYING})

STATUS_BADGES: dict[JobStatus, str] = {
    JobStatus.PENDING: "badge-pending",
    JobStatus.RUNNING: "badge-running",
    JobStatus.RETRYING: "badge-retrying",
    JobStatus.WAITING_ON_ESCALATION: "badge-escalated",
    JobStatus.SUCCEEDED: "badge-succeeded",
    JobStatus.FAILED: "badge-failed",
}

STATUS_LABELS: dict[JobStatus, str] = {
    JobStatus.PENDING: "Pending",
    JobStatus.RUNNING: "Running",
    JobStatus.RETRYING: "Retrying",
    JobStatus.WAITING_ON_ESCALATION: "Waiting on escalation",
    JobStatus.SUCCEEDED: "Succeeded",
    JobStatus.FAILED: "Failed",
}


def status_badge(status: JobStatus) -> str:
    return STATUS_BADGES[status]


def status_label(status: JobStatus) -> str:
    return STATUS_LABELS[status]


def is_active(status: JobStatus) -> bool:
    """Whether a job may still change on its own (drives live refresh)."""
    return status in ACTIVE_JOB_STATUSES


def humanize_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def _aware(moment: datetime) -> datetime:
    # SQLite hands datetimes back without a timezone; the store writes UTC.
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def elapsed_seconds(job: Job, now: datetime) -> float:
    """Time the job has been alive: up to `now` while active, otherwise up to
    its last update (so a finished job's elapsed time stops growing)."""
    end = now if is_active(job.status) else job.updated_at
    return (_aware(end) - _aware(job.created_at)).total_seconds()


@dataclass(frozen=True, slots=True)
class BudgetSummary:
    retries_used: int
    max_retries: int
    elapsed_seconds: float
    max_wall_clock_seconds: float
    retries_exhausted: bool
    wall_clock_exceeded: bool

    @property
    def elapsed_label(self) -> str:
        return humanize_duration(self.elapsed_seconds)

    @property
    def max_wall_clock_label(self) -> str:
        return humanize_duration(self.max_wall_clock_seconds)


def budget_summary(job: Job, now: datetime) -> BudgetSummary:
    elapsed = elapsed_seconds(job, now)
    return BudgetSummary(
        retries_used=job.retry_count,
        max_retries=job.budget.max_retries,
        elapsed_seconds=elapsed,
        max_wall_clock_seconds=job.budget.max_wall_clock_seconds,
        retries_exhausted=job.retry_count >= job.budget.max_retries,
        wall_clock_exceeded=elapsed >= job.budget.max_wall_clock_seconds,
    )


@dataclass(frozen=True, slots=True)
class JudgmentSummary:
    retryability: str
    confidence: float
    outcome: str

    @property
    def confidence_label(self) -> str:
        return f"{self.confidence:.0%}"


def judgment_summary(event: HistoryEvent) -> JudgmentSummary | None:
    """The classification, confidence and policy outcome of a JEV event.

    A judgment can be missing (the judge failed): the event then carries no
    output and there is nothing to summarise."""
    if event.event_type is not EventType.JEV_JUDGMENT:
        return None
    output = event.payload.get("output")
    if not isinstance(output, dict):
        return None
    return JudgmentSummary(
        retryability=str(output.get("retryability", "unknown")),
        confidence=float(output.get("confidence", 0.0)),
        outcome=str(event.payload.get("outcome", "")),
    )


@dataclass(frozen=True, slots=True)
class AttemptView:
    attempt: int
    checkpoints: list[Checkpoint]
    events: list[HistoryEvent]


def group_by_attempt(
    checkpoints: list[Checkpoint], events: list[HistoryEvent]
) -> list[AttemptView]:
    """Checkpoints and history events grouped per attempt, attempts ascending,
    each group keeping the input (chronological) order."""
    grouped_checkpoints: dict[int, list[Checkpoint]] = defaultdict(list)
    grouped_events: dict[int, list[HistoryEvent]] = defaultdict(list)
    for checkpoint in checkpoints:
        grouped_checkpoints[checkpoint.attempt].append(checkpoint)
    for event in events:
        grouped_events[event.attempt].append(event)
    attempts = sorted(set(grouped_checkpoints) | set(grouped_events))
    return [
        AttemptView(attempt, grouped_checkpoints[attempt], grouped_events[attempt])
        for attempt in attempts
    ]
