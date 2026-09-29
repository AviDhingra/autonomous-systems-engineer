"""Pure functions turning store records into display-ready values.

No HTTP, no templates, no store access: everything here is unit-testable with
plain dataclasses."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime

from jev_agent.models import (
    STEP_ORDER,
    Checkpoint,
    CheckpointPhase,
    Escalation,
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
    # A judge that raised is recorded as {"error": ...}: not a judgment.
    if not isinstance(output, dict) or "retryability" not in output:
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


@dataclass(frozen=True, slots=True)
class StepView:
    """One step of an attempt as the timeline shows it."""

    name: str
    state: str  # "done", "failed" or "started" (begun, no durable result)
    detail: str


def _resumed_note(starts: int) -> str:
    """More than one `before` checkpoint in an attempt means the step was
    re-entered: the process was interrupted mid-step and the job resumed."""
    return f" · resumed after interruption (started {starts} times)" if starts > 1 else ""


def _step_view(step: str, starts: int, after: Checkpoint | None) -> StepView:
    if after is None:
        return StepView(step, "started", "begun; no durable result")
    state = after.state
    if step == "verify":
        checks = state.get("checks")
        names = (
            ", ".join(str(c.get("name")) for c in checks if isinstance(c, dict))
            if isinstance(checks, list)
            else ""
        )
        if state.get("passed") is False:
            detail = f"checks: {names}" if names else "verification failed"
            return StepView(step, "failed", detail + _resumed_note(starts))
        detail = f"all checks passed ({names})" if names else "passed"
        return StepView(step, "done", detail + _resumed_note(starts))
    file_path = state.get("file_path")
    detail = str(file_path) if file_path else "completed"
    return StepView(step, "done", detail + _resumed_note(starts))


def step_views(checkpoints: list[Checkpoint]) -> list[StepView]:
    """The steps an attempt reached, in pipeline order, with their outcome."""
    views: list[StepView] = []
    for step in STEP_ORDER:
        starts = sum(
            1 for c in checkpoints if c.step is step and c.phase is CheckpointPhase.BEFORE
        )
        after = next(
            (c for c in checkpoints if c.step is step and c.phase is CheckpointPhase.AFTER), None
        )
        if starts == 0 and after is None:
            continue
        views.append(_step_view(step.value, starts, after))
    return views


@dataclass(frozen=True, slots=True)
class EventView:
    """A history event with a plain-language title and detail lines."""

    kind: str  # css modifier, e.g. "retry"
    title: str
    details: list[str]
    created_at: datetime
    judgment: JudgmentSummary | None = None


def _number(value: object) -> float:
    return float(value) if isinstance(value, int | float) else 0.0


def _text(value: object) -> str:
    return "" if value is None else str(value)


def event_view(event: HistoryEvent) -> EventView:
    payload = event.payload
    kind = event.event_type.value
    details: list[str] = []
    match event.event_type:
        case EventType.STATUS_TRANSITION:
            title = f"Status: {_text(payload.get('from'))} → {_text(payload.get('to'))}"
            details = [_text(payload.get("reason"))]
        case EventType.RETRY:
            title = f"Retry: attempt {_text(payload.get('from_attempt'))} failed, "
            title += f"starting attempt {_text(payload.get('to_attempt'))}"
            details = [_text(payload.get("reason"))]
        case EventType.ROLLBACK:
            title = "Rolled back the failed attempt's file change"
            details = [_text(payload.get("file_path"))]
        case EventType.JEV_JUDGMENT:
            summary = judgment_summary(event)
            if summary is None:
                title = "JEV judgment unavailable; fell back to fixed policy"
                details = [f"policy outcome: {_text(payload.get('outcome'))}"]
                output = payload.get("output")
                if isinstance(output, dict) and output.get("error"):
                    details.insert(0, _text(output["error"]))
            else:
                title = f"JEV judged the failure {summary.retryability.replace('_', ' ')}"
                details = [
                    f"confidence {summary.confidence_label}",
                    f"policy decided: {summary.outcome}",
                ]
            return EventView(kind, title, details, event.created_at, summary)
        case EventType.ESCALATION:
            title = f"Escalated: {_text(payload.get('reason'))}"
            context = payload.get("context")
            if isinstance(context, dict):
                details = [
                    f"retries {_text(context.get('retry_count'))} of "
                    f"{_text(context.get('max_retries'))}",
                    f"elapsed {humanize_duration(_number(context.get('elapsed_seconds')))} "
                    f"of {humanize_duration(_number(context.get('max_wall_clock_seconds')))}",
                ]
        case EventType.ESCALATION_RESOLVED:
            title = f"Escalation #{_text(payload.get('escalation_id'))} resolved"
            note = _text(payload.get("note"))
            details = [note] if note else []
        case EventType.STEP_ERROR:
            title = f"{_text(payload.get('step')).capitalize()} step raised an error"
            details = [f"{_text(payload.get('error_type'))}: {_text(payload.get('message'))}"]
    return EventView(kind, title, [d for d in details if d], event.created_at)


@dataclass(frozen=True, slots=True)
class AttemptDisplay:
    attempt: int
    steps: list[StepView]
    events: list[EventView]


def display_attempts(
    checkpoints: list[Checkpoint], events: list[HistoryEvent]
) -> list[AttemptDisplay]:
    return [
        AttemptDisplay(
            group.attempt,
            step_views(group.checkpoints),
            [event_view(event) for event in group.events],
        )
        for group in group_by_attempt(checkpoints, events)
    ]


REASON_LABELS = {
    "retry_budget_exhausted": "Retry budget exhausted",
    "wall_clock_exceeded": "Wall-clock budget exceeded",
    "jev_not_retryable": "JEV judged the failure not retryable",
}


@dataclass(frozen=True, slots=True)
class EscalationView:
    escalation: Escalation
    reason_label: str
    retries: str
    elapsed: str
    judgment: str
    failure_output: str
    resolved: bool


def escalation_view(escalation: Escalation) -> EscalationView:
    """Turn the stored escalation context into readable facts (no raw JSON)."""
    context = escalation.context
    judgment = context.get("judgment")
    if isinstance(judgment, dict):
        judgment_text = (
            f"{str(judgment.get('retryability', 'unknown')).replace('_', ' ')} "
            f"({float(judgment.get('confidence') or 0):.0%} confidence)"
        )
    else:
        judgment_text = "none consulted"
    return EscalationView(
        escalation=escalation,
        reason_label=REASON_LABELS.get(escalation.reason.value, escalation.reason.value),
        retries=f"{_text(context.get('retry_count'))} of {_text(context.get('max_retries'))}",
        elapsed=(
            f"{humanize_duration(_number(context.get('elapsed_seconds')))} of "
            f"{humanize_duration(_number(context.get('max_wall_clock_seconds')))}"
        ),
        judgment=judgment_text,
        failure_output=_text(context.get("failure_output")),
        resolved=escalation.resolved_at is not None,
    )
