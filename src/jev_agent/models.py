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


class StepName(StrEnum):
    PROPOSE = "propose"
    APPLY = "apply"
    VERIFY = "verify"


STEP_ORDER: tuple[StepName, ...] = (StepName.PROPOSE, StepName.APPLY, StepName.VERIFY)


class CheckpointPhase(StrEnum):
    BEFORE = "before"
    AFTER = "after"


@dataclass(frozen=True, slots=True)
class Job:
    id: str
    scenario: str
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    retry_count: int = 0


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


@dataclass(frozen=True, slots=True)
class HistoryEvent:
    id: int
    job_id: str
    attempt: int
    event_type: EventType
    payload: dict[str, object] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
