from datetime import UTC, datetime

from target.fleetops.app.services.devices import DeviceService
from target.fleetops.app.services.telemetry import TelemetryService
from target.fleetops.tests.fakes import FakeDeviceRepository, FakeTelemetryRepository


def test_same_request_id_does_not_create_second_logical_event() -> None:
    devices = FakeDeviceRepository()
    telemetry = FakeTelemetryRepository()
    device_service = DeviceService(devices)
    telemetry_service = TelemetryService(devices, telemetry)

    device = device_service.create(
        external_id="robot-001",
        firmware_version="1.4.0",
    )
    recorded_at = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)

    first = telemetry_service.ingest(
        device.id,
        request_id="retry-key-123",
        recorded_at=recorded_at,
        temperature_c=35.0,
        battery_pct=88.0,
    )
    second = telemetry_service.ingest(
        device.id,
        request_id="retry-key-123",
        recorded_at=recorded_at,
        temperature_c=35.0,
        battery_pct=88.0,
    )

    assert second.id == first.id
    assert len(telemetry.items) == 1
