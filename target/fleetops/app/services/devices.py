from uuid import uuid4
from dataclasses import replace

from ..models.domain import Device
from ..repositories.base import DeviceRepository
from .errors import DeviceNotFoundError


class DeviceService:
    def __init__(self, repository: DeviceRepository) -> None:
        self._repository = repository

    def create(
        self,
        *,
        external_id: str,
        firmware_version: str,
        display_name: str | None = None,
    ) -> Device:
        device = Device(
            id=str(uuid4()),
            external_id=external_id,
            firmware_version=firmware_version,
            display_name=display_name,
        )
        return self._repository.add(device)

    def get(self, device_id: str) -> Device:
        device = self._repository.get(device_id)
        if device is None:
            raise DeviceNotFoundError(device_id)
        return device

    def patch(self, device_id: str, *, changes: dict[str, str | None]) -> Device:
        current = self.get(device_id)
        allowed_fields = {"firmware_version", "display_name"}
        unexpected_fields = set(changes) - allowed_fields

        if unexpected_fields:
            names = ", ".join(sorted(unexpected_fields))
            raise ValueError(f"unsupported Device fields: {names}")
        
        if changes.get("firmware_version", current.firmware_version) is None:
            raise ValueError("firmware_version cannot be None")
        
        updated = replace(current, **changes)
        
        return self._repository.update(updated)
    
