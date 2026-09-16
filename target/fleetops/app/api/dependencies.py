from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from ..database import get_session
from ..repositories.sqlite import SqliteDeviceRepository, SqliteTelemetryRepository
from ..services.devices import DeviceService
from ..services.telemetry import TelemetryService


def get_device_service(session: Annotated[Session, Depends(get_session)]) -> DeviceService:
    return DeviceService(SqliteDeviceRepository(session))


def get_telemetry_service(session: Annotated[Session, Depends(get_session)]) -> TelemetryService:
    return TelemetryService(
        SqliteDeviceRepository(session),
        SqliteTelemetryRepository(session),
    )
