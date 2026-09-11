class DeviceNotFoundError(Exception):
    def __init__(self, device_id: str) -> None:
        super().__init__(f"Device not found: {device_id}")
        self.device_id = device_id