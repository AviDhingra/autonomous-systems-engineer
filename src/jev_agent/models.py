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


@dataclass(frozen=True, slots=True)
class Checkpoint:
    id: int
    job_id: str
    step: StepName
    phase: CheckpointPhase
    state: dict[str, object] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
