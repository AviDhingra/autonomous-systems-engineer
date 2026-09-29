import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Engine, create_engine, inspect, select
from sqlalchemy.orm import Session, sessionmaker

from jev_agent.db import Base, CheckpointRow, EscalationRow, ExecutionHistoryRow, JobRow
from jev_agent.models import (
    DEFAULT_BUDGET,
    NON_RUNNABLE_JOB_STATUSES,
    Budget,
    Checkpoint,
    CheckpointPhase,
    Escalation,
    EscalationReason,
    EventType,
    HistoryEvent,
    Job,
    JobStatus,
    ResolutionState,
    StepName,
)

DEFAULT_DATABASE_URL = "sqlite:///./jev_agent.db"


def _job_from_row(row: JobRow) -> Job:
    return Job(
        id=row.id,
        scenario=row.scenario,
        status=JobStatus(row.status),
        created_at=row.created_at,
        updated_at=row.updated_at,
        retry_count=row.retry_count,
        budget=Budget(
            max_retries=row.max_retries,
            max_wall_clock_seconds=row.max_wall_clock_seconds,
        ),
    )


def _checkpoint_from_row(row: CheckpointRow) -> Checkpoint:
    return Checkpoint(
        id=row.id,
        job_id=row.job_id,
        step=StepName(row.step),
        phase=CheckpointPhase(row.phase),
        attempt=row.attempt,
        state=json.loads(row.state),
        created_at=row.created_at,
    )


def _history_from_row(row: ExecutionHistoryRow) -> HistoryEvent:
    return HistoryEvent(
        id=row.id,
        job_id=row.job_id,
        attempt=row.attempt,
        event_type=EventType(row.event_type),
        payload=json.loads(row.payload),
        created_at=row.created_at,
    )


def _escalation_from_row(row: EscalationRow) -> Escalation:
    return Escalation(
        id=row.id,
        job_id=row.job_id,
        attempt=row.attempt,
        reason=EscalationReason(row.reason),
        context=json.loads(row.context),
        created_at=row.created_at,
        resolution_state=ResolutionState(row.resolution_state),
        resolved_at=row.resolved_at,
    )


def _history_row(
    job_id: str, attempt: int, event_type: EventType, payload: dict[str, object]
) -> ExecutionHistoryRow:
    return ExecutionHistoryRow(
        job_id=job_id,
        attempt=attempt,
        event_type=event_type.value,
        payload=json.dumps(payload),
        created_at=datetime.now(UTC),
    )


def _check_schema(engine: Engine) -> None:
    """Fail clearly if an existing database predates the current schema.

    `create_all` never alters an existing table, so a store file written by an
    older milestone would otherwise fail later with an obscure SQL error. This
    is dev/demo state: the fix is to move or delete the file, not to migrate it.
    """
    inspector = inspect(engine)
    for table in Base.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue
        existing = {column["name"] for column in inspector.get_columns(table.name)}
        missing = sorted({column.name for column in table.columns} - existing)
        if missing:
            raise RuntimeError(
                f"{engine.url.database} has an outdated schema: table '{table.name}' "
                f"lacks column(s) {', '.join(missing)}. It is disposable dev state; "
                "move or delete the file and run again."
            )


class JobStore:
    """Durable SQLite-backed store for jobs, checkpoints, history, and escalations.

    Separate from FleetOps's own `fleetops.db` — this store only ever
    tracks Project 2's governance state, never FleetOps application data.

    State changes that history must describe (`transition`,
    `increment_retry_count`, `escalate`) write the change and its history
    event in one transaction, so the two can never drift apart.
    """

    def __init__(self, database_url: str = DEFAULT_DATABASE_URL) -> None:
        self._engine = create_engine(database_url, connect_args={"check_same_thread": False})
        self._session_factory = sessionmaker(
            bind=self._engine,
            class_=Session,
            autoflush=False,
            expire_on_commit=False,
        )
        _check_schema(self._engine)
        Base.metadata.create_all(self._engine)

    def create_job(self, scenario: str, budget: Budget = DEFAULT_BUDGET) -> Job:
        now = datetime.now(UTC)
        row = JobRow(
            id=str(uuid4()),
            scenario=scenario,
            status=JobStatus.PENDING.value,
            created_at=now,
            updated_at=now,
            retry_count=0,
            max_retries=budget.max_retries,
            max_wall_clock_seconds=budget.max_wall_clock_seconds,
        )
        with self._session_factory() as session:
            session.add(row)
            session.commit()
        return _job_from_row(row)

    def get_job(self, job_id: str) -> Job | None:
        with self._session_factory() as session:
            row = session.get(JobRow, job_id)
            if row is None:
                return None
            return _job_from_row(row)

    def find_active_job(self, scenario: str) -> Job | None:
        """Return the most recent runnable job for a scenario, if any.

        Finished jobs and jobs waiting on an escalation are not offered for
        resumption."""
        non_runnable = {status.value for status in NON_RUNNABLE_JOB_STATUSES}
        with self._session_factory() as session:
            rows = session.scalars(
                select(JobRow)
                .where(JobRow.scenario == scenario)
                .order_by(JobRow.created_at.desc())
            )
            for row in rows:
                if row.status not in non_runnable:
                    return _job_from_row(row)
        return None

    def update_job_status(self, job_id: str, status: JobStatus) -> Job:
        """Low-level status write with no history event. The runner uses
        `transition`, which records why; this exists for seeding state."""
        with self._session_factory() as session:
            row = session.get(JobRow, job_id)
            if row is None:
                raise KeyError(job_id)
            row.status = status.value
            row.updated_at = datetime.now(UTC)
            session.commit()
            return _job_from_row(row)

    def transition(self, job_id: str, status: JobStatus, attempt: int, reason: str) -> Job:
        """Change a job's status and record a `STATUS_TRANSITION` event in one
        transaction. A no-op (no write, no event) if the status is unchanged."""
        with self._session_factory() as session:
            row = session.get(JobRow, job_id)
            if row is None:
                raise KeyError(job_id)
            previous = row.status
            if previous == status.value:
                return _job_from_row(row)
            row.status = status.value
            row.updated_at = datetime.now(UTC)
            session.add(
                _history_row(
                    job_id,
                    attempt,
                    EventType.STATUS_TRANSITION,
                    {"from": previous, "to": status.value, "reason": reason},
                )
            )
            session.commit()
            return _job_from_row(row)

    def increment_retry_count(self, job_id: str, reason: str = "") -> Job:
        """Bump a job's retry count by one, marking the start of a new attempt,
        and record a `RETRY` event in the same transaction."""
        with self._session_factory() as session:
            row = session.get(JobRow, job_id)
            if row is None:
                raise KeyError(job_id)
            failed_attempt = row.retry_count + 1
            row.retry_count += 1
            row.updated_at = datetime.now(UTC)
            session.add(
                _history_row(
                    job_id,
                    failed_attempt,
                    EventType.RETRY,
                    {
                        "from_attempt": failed_attempt,
                        "to_attempt": failed_attempt + 1,
                        "reason": reason,
                    },
                )
            )
            session.commit()
            return _job_from_row(row)

    def escalate(
        self,
        job_id: str,
        attempt: int,
        reason: EscalationReason,
        context: dict[str, object],
    ) -> Escalation:
        """Record an escalation and move the job to `WAITING_ON_ESCALATION`,
        with its `STATUS_TRANSITION` and `ESCALATION` events, in one transaction."""
        now = datetime.now(UTC)
        with self._session_factory() as session:
            job_row = session.get(JobRow, job_id)
            if job_row is None:
                raise KeyError(job_id)
            previous = job_row.status
            job_row.status = JobStatus.WAITING_ON_ESCALATION.value
            job_row.updated_at = now
            escalation_row = EscalationRow(
                job_id=job_id,
                attempt=attempt,
                reason=reason.value,
                context=json.dumps(context),
                created_at=now,
                resolution_state=ResolutionState.PENDING.value,
                resolved_at=None,
            )
            session.add(escalation_row)
            session.add(
                _history_row(
                    job_id,
                    attempt,
                    EventType.STATUS_TRANSITION,
                    {
                        "from": previous,
                        "to": JobStatus.WAITING_ON_ESCALATION.value,
                        "reason": f"escalated: {reason.value}",
                    },
                )
            )
            session.add(
                _history_row(
                    job_id,
                    attempt,
                    EventType.ESCALATION,
                    {"reason": reason.value, "context": context},
                )
            )
            session.commit()
            session.refresh(escalation_row)
            return _escalation_from_row(escalation_row)

    def list_escalations(self, job_id: str) -> list[Escalation]:
        with self._session_factory() as session:
            rows = session.scalars(
                select(EscalationRow)
                .where(EscalationRow.job_id == job_id)
                .order_by(EscalationRow.id.asc())
            )
            return [_escalation_from_row(row) for row in rows]

    def add_checkpoint(
        self,
        job_id: str,
        step: StepName,
        phase: CheckpointPhase,
        state: dict[str, object] | None = None,
        attempt: int = 1,
    ) -> Checkpoint:
        row = CheckpointRow(
            job_id=job_id,
            step=step.value,
            phase=phase.value,
            attempt=attempt,
            state=json.dumps(state or {}),
            created_at=datetime.now(UTC),
        )
        with self._session_factory() as session:
            session.add(row)
            session.commit()
            session.refresh(row)
            return _checkpoint_from_row(row)

    def list_checkpoints(self, job_id: str) -> list[Checkpoint]:
        with self._session_factory() as session:
            rows = session.scalars(
                select(CheckpointRow)
                .where(CheckpointRow.job_id == job_id)
                .order_by(CheckpointRow.id.asc())
            )
            return [_checkpoint_from_row(row) for row in rows]

    def append_history_event(
        self,
        job_id: str,
        attempt: int,
        event_type: EventType,
        payload: dict[str, object],
    ) -> HistoryEvent:
        """Append one event to the job's execution history. Append-only: there
        is deliberately no update or delete counterpart."""
        row = _history_row(job_id, attempt, event_type, payload)
        with self._session_factory() as session:
            session.add(row)
            session.commit()
            session.refresh(row)
            return _history_from_row(row)

    def append_history_event_once(
        self,
        job_id: str,
        attempt: int,
        event_type: EventType,
        payload: dict[str, object],
    ) -> HistoryEvent | None:
        """Like `append_history_event`, but skipped (returning None) if the job
        already has an event of this type for this attempt. Keeps crash-replayed
        steps from duplicating their history."""
        with self._session_factory() as session:
            existing = session.scalars(
                select(ExecutionHistoryRow.id).where(
                    ExecutionHistoryRow.job_id == job_id,
                    ExecutionHistoryRow.attempt == attempt,
                    ExecutionHistoryRow.event_type == event_type.value,
                )
            ).first()
            if existing is not None:
                return None
            row = _history_row(job_id, attempt, event_type, payload)
            session.add(row)
            session.commit()
            session.refresh(row)
            return _history_from_row(row)

    def list_history(self, job_id: str) -> list[HistoryEvent]:
        with self._session_factory() as session:
            rows = session.scalars(
                select(ExecutionHistoryRow)
                .where(ExecutionHistoryRow.job_id == job_id)
                .order_by(ExecutionHistoryRow.id.asc())
            )
            return [_history_from_row(row) for row in rows]
