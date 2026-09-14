from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.db import DeviceRow, TelemetryRow
from ..models.domain import Device, Telemetry


def _device_from_row(row: DeviceRow) -> Device:
    return Device(
        id=row.id,
        external_id=row.external_id,
        firmware_version=row.firmware_version,
        display_name=row.display_name,
    )


def _telemetry_from_row(row: TelemetryRow) -> Telemetry:
    return Telemetry(
        id=row.id,
        device_id=row.device_id,
        request_id=row.request_id,
        recorded_at=row.recorded_at,
        temperature_c=row.temperature_c,
        battery_pct=row.battery_pct,
    )


class SqliteDeviceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, device: Device) -> Device:
        self._session.add(
            DeviceRow(
                id=device.id,
                external_id=device.external_id,
                firmware_version=device.firmware_version,
                display_name=device.display_name,
            )
        )
        self._session.commit()
        return device

    def get(self, device_id: str) -> Device | None:
        row = self._session.get(DeviceRow, device_id)
        if row is None:
            return None
        return _device_from_row(row)

    def update(self, device: Device) -> Device:
        row = self._session.get(DeviceRow, device.id)
        if row is None:
            raise KeyError(device.id)
        row.firmware_version = device.firmware_version
        row.display_name = device.display_name
        self._session.commit()
        return _device_from_row(row)


class SqliteTelemetryRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, telemetry: Telemetry) -> Telemetry:
        self._session.add(
            TelemetryRow(
                id=telemetry.id,
                device_id=telemetry.device_id,
                request_id=telemetry.request_id,
                recorded_at=telemetry.recorded_at,
                temperature_c=telemetry.temperature_c,
                battery_pct=telemetry.battery_pct,
            )
        )
        self._session.commit()
        return telemetry

    def get_by_request(self, device_id: str, request_id: str) -> Telemetry | None:
        row = self._session.scalar(
            select(TelemetryRow).where(
                TelemetryRow.device_id == device_id,
                TelemetryRow.request_id == request_id,
            )
        )
        if row is None:
            return None
        return _telemetry_from_row(row)

    def list_for_device(self, device_id: str, *, limit: int = 100) -> list[Telemetry]:
        rows = self._session.scalars(
            select(TelemetryRow)
            .where(TelemetryRow.device_id == device_id)
            .order_by(TelemetryRow.recorded_at.desc())
            .limit(limit)
        )
        return [_telemetry_from_row(row) for row in rows]