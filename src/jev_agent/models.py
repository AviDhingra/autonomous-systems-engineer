from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    RETRYING = "retrying"
    WAITING_ON_ESCALATION = "waiting_on_escalation"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


TERMINAL_JOB_STATUSES = frozenset({JobStatus.SUCCEEDED, JobStatus.FAILED})

# Statuses the runner never resumes: finished, or stopped for a human. An
# escalated job is "terminal for now" — only a (later) manual resolution moves it.
NON_RUNNABLE_JOB_STATUSES = TERMINAL_JOB_STATUSES | {JobStatus.WAITING_ON_ESCALATION}


class StepName(StrEnum):
    PROPOSE = "propose"
    APPLY = "apply"
    VERIFY = "verify"


STEP_ORDER: tuple[StepName, ...] = (StepName.PROPOSE, StepName.APPLY, StepName.VERIFY)


class CheckpointPhase(StrEnum):
    BEFORE = "before"
    AFTER = "after"


@dataclass(frozen=True, slots=True)
class Budget:
    """Per-job limits. Exceeding either forces policy to ESCALATE."""

    max_retries: int
    max_wall_clock_seconds: float


DEFAULT_MAX_RETRIES = 2
DEFAULT_MAX_WALL_CLOCK_SECONDS = 1800.0
DEFAULT_BUDGET = Budget(
    max_retries=DEFAULT_MAX_RETRIES,
    max_wall_clock_seconds=DEFAULT_MAX_WALL_CLOCK_SECONDS,
)


@dataclass(frozen=True, slots=True)
class Job:
    id: str
    scenario: str
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    retry_count: int = 0
    budget: Budget = DEFAULT_BUDGET


@dataclass(frozen=True, slots=True)
class Checkpoint:
    id: int
    job_id: str
    step: StepName
    phase: CheckpointPhase
    attempt: int = 1
    state: dict[str, object] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class Retryability(StrEnum):
    RETRYABLE = "retryable"
    NOT_RETRYABLE = "not_retryable"


@dataclass(frozen=True, slots=True)
class Judgment:
    """A bounded JEV classification of a VERIFY failure. Data only: policy
    consumes it, it never causes a state change by itself."""

    retryability: Retryability
    confidence: float


class EventType(StrEnum):
    JEV_JUDGMENT = "jev_judgment"
    STEP_ERROR = "step_error"
    STATUS_TRANSITION = "status_transition"
    RETRY = "retry"
    ROLLBACK = "rollback"
    ESCALATION = "escalation"


@dataclass(frozen=True, slots=True)
class HistoryEvent:
    id: int
    job_id: str
    attempt: int
    event_type: EventType
    payload: dict[str, object] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class EscalationReason(StrEnum):
    RETRY_BUDGET_EXHAUSTED = "retry_budget_exhausted"
    WALL_CLOCK_EXCEEDED = "wall_clock_exceeded"
    JEV_NOT_RETRYABLE = "jev_not_retryable"


class ResolutionState(StrEnum):
    PENDING = "pending"
    RESOLVED = "resolved"


@dataclass(frozen=True, slots=True)
class Escalation:
    id: int
    job_id: str
    attempt: int
    reason: EscalationReason
    context: dict[str, object]
    created_at: datetime
    resolution_state: ResolutionState = ResolutionState.PENDING
    resolved_at: datetime | None = None
