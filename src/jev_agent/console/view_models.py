"""Pure functions turning store records into display-ready values.

No HTTP, no templates, no store access: everything here is unit-testable with
plain dataclasses."""

from collections import defaultdict
from collections.abc import Callable
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

    @property
    def actor(self) -> "Actor":
        return event_actor(self.kind)


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
        # Either JEV was unavailable or no judgment was due (a budget ran out
        # before the attempt started); either way policy did not rely on one.
        judgment_text = "no usable judgment"
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


# --- Actors: who does what, and who holds authority -------------------------


@dataclass(frozen=True, slots=True)
class Actor:
    key: str
    label: str
    role: str


ACTORS: dict[str, Actor] = {
    actor.key: actor
    for actor in (
        Actor(
            "model",
            "Frontier model",
            "Investigates the bug and proposes one file change. Never decides what happens next.",
        ),
        Actor(
            "python",
            "Python step",
            "Applies the proposed change and runs pytest, Ruff and mypy.",
        ),
        Actor(
            "jev",
            "JEV judgment",
            "A narrow, bounded classification: is this failure worth retrying? "
            "Advice only, never authority.",
        ),
        Actor(
            "policy",
            "Deterministic policy",
            "Plain Python that alone decides: retry, escalate, succeed or fail, within budget.",
        ),
        Actor(
            "human",
            "Person",
            "Resolves escalations: the cases the system will not guess about.",
        ),
    )
}

STEP_ACTORS = {"propose": "model", "apply": "python", "verify": "python"}

EVENT_ACTORS = {
    EventType.STATUS_TRANSITION.value: "policy",
    EventType.RETRY.value: "policy",
    EventType.ROLLBACK.value: "policy",
    EventType.JEV_JUDGMENT.value: "jev",
    EventType.ESCALATION.value: "policy",
    EventType.ESCALATION_RESOLVED.value: "human",
    EventType.STEP_ERROR.value: "python",
}


def event_actor(kind: str) -> Actor:
    return ACTORS[EVENT_ACTORS.get(kind, "policy")]


def step_actor(step: str) -> Actor:
    return ACTORS[STEP_ACTORS.get(step, "python")]


# --- Pipeline stepper and decision nodes ------------------------------------

STEP_LABELS = {"propose": "Propose", "apply": "Apply", "verify": "Verify"}


@dataclass(frozen=True, slots=True)
class PipelineStep:
    """One box of the Propose -> Apply -> Verify track.

    `state` is one of: done, failed, running, interrupted, pending."""

    name: str
    state: str
    detail: str

    @property
    def label(self) -> str:
        return STEP_LABELS.get(self.name, self.name.capitalize())

    @property
    def actor(self) -> Actor:
        return step_actor(self.name)


def pipeline_steps(checkpoints: list[Checkpoint], unfinished_state: str) -> list[PipelineStep]:
    """All three steps of one attempt, including ones not reached yet.

    A step that started but has no durable result is shown as
    `unfinished_state`: "running" while the job is live, "interrupted" when a
    crash left it mid-step, "failed" when the step raised."""
    steps: list[PipelineStep] = []
    blocked = False
    for step in STEP_ORDER:
        starts = sum(
            1 for c in checkpoints if c.step is step and c.phase is CheckpointPhase.BEFORE
        )
        after = next(
            (c for c in checkpoints if c.step is step and c.phase is CheckpointPhase.AFTER), None
        )
        if blocked or (starts == 0 and after is None):
            steps.append(PipelineStep(step.value, "pending", "not reached"))
            continue
        if after is None:
            detail = {
                "running": "in progress…",
                "interrupted": "interrupted mid-step; resume continues here",
                "failed": "raised an error",
            }.get(unfinished_state, "no durable result")
            steps.append(PipelineStep(step.value, unfinished_state, detail))
            blocked = True
            continue
        view = _step_view(step.value, starts, after)
        steps.append(PipelineStep(step.value, view.state, view.detail))
        if view.state == "failed":
            blocked = True
    return steps


OUTCOME_LABELS = {"retry": "Retry", "escalate": "Escalate", "fail": "Fail"}


@dataclass(frozen=True, slots=True)
class DecisionView:
    """What happened after an attempt's VERIFY failed: JEV's view, then
    policy's decision, with the budget as it stood at that moment."""

    attempt: int
    judgment: JudgmentSummary | None
    jev_error: str | None
    outcome: str
    escalation_reason: str | None
    retries: str
    elapsed: str
    explanation: str

    @property
    def outcome_label(self) -> str:
        return OUTCOME_LABELS.get(self.outcome, self.outcome.capitalize())


def _decision_explanation(
    outcome: str, judgment: JudgmentSummary | None, reason: str | None
) -> str:
    if outcome == "escalate":
        if reason == "retry_budget_exhausted":
            return "The retry budget was spent, so policy escalated regardless of JEV's view."
        if reason == "wall_clock_exceeded":
            return "The time budget was spent, so policy escalated regardless of JEV's view."
        return (
            "JEV was confident the failure is not retryable, so policy escalated "
            "to a person instead of guessing."
        )
    if outcome == "retry":
        if judgment is None:
            return (
                "JEV was unavailable, so policy applied its fixed rule: "
                "retry while budget remains."
            )
        if judgment.retryability == "not_retryable":
            return (
                "JEV's confidence was below policy's threshold, so policy set it aside "
                "and retried within budget."
            )
        return "JEV judged the failure retryable and budget remains, so policy retried."
    if outcome == "fail":
        return "Policy ended the job as failed."
    return ""


def decision_view(job: Job, attempt: int, events: list[HistoryEvent]) -> DecisionView | None:
    """The decision node for one attempt, or None if its VERIFY did not fail
    (no JEV judgment was consulted)."""
    jev = next((e for e in events if e.event_type is EventType.JEV_JUDGMENT), None)
    if jev is None:
        return None
    judgment = judgment_summary(jev)
    output = jev.payload.get("output")
    error = (
        _text(output.get("error"))
        if judgment is None and isinstance(output, dict) and output.get("error")
        else None
    )
    escalation = next((e for e in events if e.event_type is EventType.ESCALATION), None)
    reason = _text(escalation.payload.get("reason")) if escalation is not None else None
    outcome = _text(jev.payload.get("outcome"))
    elapsed = (_aware(jev.created_at) - _aware(job.created_at)).total_seconds()
    return DecisionView(
        attempt=attempt,
        judgment=judgment,
        jev_error=error,
        outcome=outcome,
        escalation_reason=REASON_LABELS.get(reason, reason) if reason else None,
        retries=f"{attempt - 1} of {job.budget.max_retries} retries used",
        elapsed=(
            f"{humanize_duration(elapsed)} of "
            f"{humanize_duration(job.budget.max_wall_clock_seconds)} used"
        ),
        explanation=_decision_explanation(outcome, judgment, reason),
    )


@dataclass(frozen=True, slots=True)
class AttemptTrack:
    """One attempt as the job page draws it: stepper, decision, timeline."""

    attempt: int
    pipeline: list[PipelineStep]
    decision: DecisionView | None
    events: list[EventView]


def job_tracks(
    job: Job,
    checkpoints: list[Checkpoint],
    events: list[HistoryEvent],
    *,
    live: bool,
    interrupted: bool,
) -> list[AttemptTrack]:
    """Every attempt of `job`, oldest first. Only the latest attempt can be
    running or interrupted; a job with no checkpoints yet shows one pending
    attempt so the stepper is never empty."""
    groups = group_by_attempt(checkpoints, events) or [AttemptView(1, [], [])]
    latest = groups[-1].attempt
    tracks: list[AttemptTrack] = []
    for group in groups:
        if group.attempt == latest and interrupted:
            unfinished = "interrupted"
        elif group.attempt == latest and live:
            unfinished = "running"
        else:
            unfinished = "failed"
        tracks.append(
            AttemptTrack(
                attempt=group.attempt,
                pipeline=pipeline_steps(group.checkpoints, unfinished),
                decision=decision_view(job, group.attempt, group.events),
                events=[event_view(event) for event in group.events],
            )
        )
    return tracks


# --- Jobs list and dashboard --------------------------------------------------


@dataclass(frozen=True, slots=True)
class JobListItem:
    job: Job
    badge: str
    label: str
    elapsed: str
    story_title: str | None
    interrupted: bool


def job_list_item(
    job: Job, now: datetime, interrupted: bool, story_titles: dict[str, str]
) -> JobListItem:
    badge, label = status_badge(job.status), status_label(job.status)
    if interrupted:
        badge, label = "badge-interrupted", "Interrupted"
    return JobListItem(
        job=job,
        badge=badge,
        label=label,
        elapsed=humanize_duration(elapsed_seconds(job, now)),
        story_title=story_titles.get(job.simulation, job.simulation) if job.simulation else None,
        interrupted=interrupted,
    )


@dataclass(frozen=True, slots=True)
class StatusSlice:
    status: JobStatus
    label: str
    badge: str
    count: int
    percent: float


@dataclass(frozen=True, slots=True)
class DashboardStats:
    total: int
    succeeded: int
    failed: int
    waiting: int
    active: int
    retries: int
    simulated: int
    pending_escalations: int
    breakdown: list[StatusSlice]

    @property
    def success_rate_label(self) -> str:
        finished = self.succeeded + self.failed + self.waiting
        return f"{self.succeeded / finished:.0%}" if finished else "–"


def dashboard_stats(jobs: list[Job], pending_escalations: int) -> DashboardStats:
    counts = {status: 0 for status in JobStatus}
    for job in jobs:
        counts[job.status] += 1
    total = len(jobs)
    breakdown = [
        StatusSlice(
            status=status,
            label=status_label(status),
            badge=status_badge(status),
            count=counts[status],
            percent=(counts[status] / total * 100) if total else 0.0,
        )
        for status in JobStatus
        if counts[status]
    ]
    return DashboardStats(
        total=total,
        succeeded=counts[JobStatus.SUCCEEDED],
        failed=counts[JobStatus.FAILED],
        waiting=counts[JobStatus.WAITING_ON_ESCALATION],
        active=sum(counts[status] for status in ACTIVE_JOB_STATUSES),
        retries=sum(job.retry_count for job in jobs),
        simulated=sum(1 for job in jobs if job.simulation is not None),
        pending_escalations=pending_escalations,
        breakdown=breakdown,
    )


# --- Guided tour ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TourStep:
    key: str
    title: str
    explanation: str
    story_name: str | None
    latest_job: Job | None


TOUR: tuple[tuple[str, str, str, str | None], ...] = (
    (
        "pipeline",
        "A governed pipeline",
        "A frontier model proposes a fix for a real bug; Python applies it and runs the "
        "project's checks. Each step is checkpointed before it starts and after it "
        "finishes, so the store always knows exactly how far a job got.",
        "happy-path",
    ),
    (
        "recovery",
        "Crashes don't lose work",
        "If the process dies mid-run, the job is resumed from its checkpoints: completed "
        "steps are never redone, and the interrupted step is re-entered. No re-proposing, "
        "no double-applying the same change.",
        "crash-resume",
    ),
    (
        "retry",
        "Bounded retry with rollback",
        "When verification fails, the failed change is rolled back and a fresh attempt "
        "starts from Propose, a limited number of times. Never an infinite loop.",
        "retry-then-pass",
    ),
    (
        "judgment",
        "JEV advises, policy decides",
        "At one point, whether a failure is worth retrying, a narrow JEV judgment is "
        "consulted through the live API. Its answer is one input: deterministic Python "
        "policy makes the actual decision, and falls back to a fixed rule if JEV is "
        "unavailable or unsure.",
        "jev-stop",
    ),
    (
        "budgets",
        "Budgets force escalation",
        "Every job has a retry budget and a time budget. When either is spent, policy "
        "escalates whatever JEV says, with a durable record of exactly why.",
        "retry-budget",
    ),
    (
        "human",
        "A person closes the loop",
        "Escalated jobs wait for a person. Resolving an escalation records the note and "
        "the time; it never restarts the job behind anyone's back.",
        None,
    ),
)


def tour_steps(latest_job: Callable[[str], Job | None]) -> list[TourStep]:
    return [
        TourStep(
            key=key,
            title=title,
            explanation=explanation,
            story_name=story,
            latest_job=latest_job(story) if story else None,
        )
        for key, title, explanation, story in TOUR
    ]
