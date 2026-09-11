import pytest

from target.fleetops.app.services.devices import DeviceService
from target.fleetops.app.services.errors import DeviceNotFoundError
from target.fleetops.tests.fakes import FakeDeviceRepository


def test_create_and_get_device() -> None:
    service = DeviceService(FakeDeviceRepository())
    created = service.create(
        external_id="robot-001",
        firmware_version="1.4.0",
        display_name="Sorter A",
    )

    assert service.get(created.id) == created


def test_get_missing_device_raises_application_error() -> None:
    service = DeviceService(FakeDeviceRepository())

    with pytest.raises(DeviceNotFoundError):
        service.get("missing")


def test_patch_preserves_omitted_fields() -> None:
    service = DeviceService(FakeDeviceRepository())
    created = service.create(
        external_id="robot-001",
        firmware_version="1.4.0",
        display_name="Sorter A",
    )

    updated = service.patch(created.id, changes={"firmware_version": "1.5.0"})

    assert updated.firmware_version == "1.5.0"
    assert updated.display_name == "Sorter A"