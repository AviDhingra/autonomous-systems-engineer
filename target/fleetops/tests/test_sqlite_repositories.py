from pathlib import Path
from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from target.fleetops.app.models.db import Base
from target.fleetops.app.models.domain import Device, Telemetry
from target.fleetops.app.repositories.sqlite import SqliteDeviceRepository, SqliteTelemetryRepository


def test_sqlite_repositories_persist_and_read(tmp_path: Path) -> None:
    database_path = tmp_path / "fleetops-test.db"
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        devices = SqliteDeviceRepository(session)
        telemetry = SqliteTelemetryRepository(session)
        device = Device(
            id="device-1",
            external_id="robot-001",
            firmware_version="1.4.0",
        )
        devices.add(device)
        telemetry.add(
            Telemetry(
                id="telemetry-1",
                device_id=device.id,
                request_id="req-1",
                recorded_at=datetime(2026, 9, 5, 12, 0, tzinfo=UTC),
                temperature_c=35.0,
                battery_pct=90.0,
            )
        )

        assert devices.get(device.id) == device
        assert telemetry.get_by_request(device.id, "req-1") is not None
