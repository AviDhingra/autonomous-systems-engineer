import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from jev_agent.db import Base, CheckpointRow, JobRow
from jev_agent.models import (
    TERMINAL_JOB_STATUSES,
    Checkpoint,
    CheckpointPhase,
    Job,
    JobStatus,
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


class JobStore:
    """Durable SQLite-backed store for jobs and their checkpoints.

    Separate from FleetOps's own `fleetops.db` — this store only ever
    tracks Project 2's governance state, never FleetOps application data.
    """

    def __init__(self, database_url: str = DEFAULT_DATABASE_URL) -> None:
        self._engine = create_engine(database_url, connect_args={"check_same_thread": False})
        self._session_factory = sessionmaker(
            bind=self._engine,
            class_=Session,
            autoflush=False,
            expire_on_commit=False,
        )
        Base.metadata.create_all(self._engine)

    def create_job(self, scenario: str) -> Job:
        now = datetime.now(UTC)
        row = JobRow(
            id=str(uuid4()),
            scenario=scenario,
            status=JobStatus.PENDING.value,
            created_at=now,
            updated_at=now,
            retry_count=0,
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
        """Return the most recent non-terminal job for a scenario, if any."""
        terminal = {status.value for status in TERMINAL_JOB_STATUSES}
        with self._session_factory() as session:
            rows = session.scalars(
                select(JobRow)
                .where(JobRow.scenario == scenario)
                .order_by(JobRow.created_at.desc())
            )
            for row in rows:
                if row.status not in terminal:
                    return _job_from_row(row)
        return None

    def update_job_status(self, job_id: str, status: JobStatus) -> Job:
        with self._session_factory() as session:
            row = session.get(JobRow, job_id)
            if row is None:
                raise KeyError(job_id)
            row.status = status.value
            row.updated_at = datetime.now(UTC)
            session.commit()
            return _job_from_row(row)

    def increment_retry_count(self, job_id: str) -> Job:
        """Bump a job's retry count by one, marking the start of a new attempt."""
        with self._session_factory() as session:
            row = session.get(JobRow, job_id)
            if row is None:
                raise KeyError(job_id)
            row.retry_count += 1
            row.updated_at = datetime.now(UTC)
            session.commit()
            return _job_from_row(row)

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
