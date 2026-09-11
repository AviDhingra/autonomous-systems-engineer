from datetime import UTC, datetime

from target.fleetops.app.models.domain import Device, Telemetry
from fleetops.tests.fakes import FakeDeviceRepository, FakeTelemetryRepository


def test_fake_device_repository_add_and_get() -> None:
    repository = FakeDeviceRepository()
    device = Device(
        id="device-1",
        external_id="robot-001",
        firmware_version="1.4.0",
    )

    repository.add(device)

    assert repository.get(device.id) == device


def test_fake_telemetry_repository_finds_logical_request() -> None:
    repository = FakeTelemetryRepository()
    telemetry = Telemetry(
        id="telemetry-1",
        device_id="device-1",
        request_id="request-1",
        recorded_at=datetime(2026, 9, 5, 12, 0, tzinfo=UTC),
        temperature_c=35.0,
        battery_pct=90.0,
    )
    repository.add(telemetry)

    assert repository.get_by_request("device-1", "request-1") == telemetry