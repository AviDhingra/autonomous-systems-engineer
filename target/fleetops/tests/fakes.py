from target.fleetops.app.models.domain import Device, Telemetry


class FakeDeviceRepository:
    def __init__(self) -> None:
        self.items: dict[str, Device] = {}

    def add(self, device: Device) -> Device:
        self.items[device.id] = device
        return device

    def get(self, device_id: str) -> Device | None:
        return self.items.get(device_id)

    def update(self, device: Device) -> Device:
        if device.id not in self.items:
            raise KeyError(device.id)
        self.items[device.id] = device
        return device


class FakeTelemetryRepository:
    def __init__(self) -> None:
        self.items: list[Telemetry] = []

    def add(self, telemetry: Telemetry) -> Telemetry:
        self.items.append(telemetry)
        return telemetry

    def get_by_request(self, device_id: str, request_id: str) -> Telemetry | None:
        for item in self.items:
            if item.device_id == device_id and item.request_id == request_id:
                return item
        return None

    def list_for_device(self, device_id: str, *, limit: int = 100) -> list[Telemetry]:
        matching = [item for item in self.items if item.device_id == device_id]
        newest_first = sorted(matching, key=lambda item: item.recorded_at, reverse=True)
        return newest_first[:limit]