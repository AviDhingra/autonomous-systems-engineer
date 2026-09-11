from datetime import UTC, datetime, timedelta

from target.fleetops.app.models.domain import DeviceHealth
from target.fleetops.app.services.devices import DeviceService
from target.fleetops.app.services.telemetry import TelemetryService
from target.fleetops.tests.fakes import FakeDeviceRepository, FakeTelemetryRepository


def _services() -> tuple[DeviceService, TelemetryService, FakeTelemetryRepository]:
    devices = FakeDeviceRepository()
    telemetry = FakeTelemetryRepository()
    return DeviceService(devices), TelemetryService(devices, telemetry), telemetry


def test_retry_is_idempotent() -> None:
    device_service, telemetry_service, telemetry_repo = _services()
    device = device_service.create(external_id="robot-001", firmware_version="1.4.0")
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)

    first = telemetry_service.ingest(
        device.id,
        request_id="req-123",
        recorded_at=now,
        temperature_c=35.0,
        battery_pct=90.0,
    )
    second = telemetry_service.ingest(
        device.id,
        request_id="req-123",
        recorded_at=now,
        temperature_c=35.0,
        battery_pct=90.0,
    )

    assert second.id == first.id
    assert len(telemetry_repo.items) == 1


def test_stale_telemetry_reports_stale() -> None:
    device_service, telemetry_service, _ = _services()
    device = device_service.create(external_id="robot-001", firmware_version="1.4.0")
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    telemetry_service.ingest(
        device.id,
        request_id="old",
        recorded_at=now - timedelta(minutes=10),
        temperature_c=35.0,
        battery_pct=90.0,
    )

    health, _ = telemetry_service.health(device.id, now=now)

    assert health is DeviceHealth.STALE