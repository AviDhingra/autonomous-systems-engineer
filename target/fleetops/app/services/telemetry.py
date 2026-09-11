from datetime import UTC, datetime, timedelta
from uuid import uuid4


from ..models.domain import Telemetry, DeviceHealth
from ..repositories.base import DeviceRepository, TelemetryRepository
from .errors import DeviceNotFoundError


class TelemetryService:
    def __init__(self, devices: DeviceRepository, telemetry: TelemetryRepository) -> None:
        self._devices = devices
        self._telemetry = telemetry

    def ingest(
        self,
        device_id: str,
        *,
        request_id: str,
        recorded_at: datetime,
        temperature_c: float,
        battery_pct: float,
    ) -> Telemetry:
        if self._devices.get(device_id) is None:
            raise DeviceNotFoundError(device_id)

        existing = self._telemetry.get_by_request(device_id, request_id)
        if existing is not None:
            return existing

        record = Telemetry(
            id=str(uuid4()),
            device_id=device_id,
            request_id=request_id,
            recorded_at=recorded_at,
            temperature_c=temperature_c,
            battery_pct=battery_pct,
        )
        return self._telemetry.add(record)
    

    def list_for_device(self, device_id: str, *, limit: int = 100) -> list[Telemetry]:
        if self._devices.get(device_id) is None:
            raise DeviceNotFoundError(device_id)
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        return self._telemetry.list_for_device(device_id, limit=limit)

    def health(
        self,
        device_id: str,
        *,
        now: datetime | None = None,
    ) -> tuple[DeviceHealth, datetime | None]:

        five_minutes = timedelta(minutes=5)
        
        if self._devices.get(device_id) is None:
            raise DeviceNotFoundError(device_id)

        records = self._telemetry.list_for_device(device_id, limit=1)
        if not records:
            return DeviceHealth.UNKNOWN, None

        last_seen = records[0].recorded_at
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=UTC)
        reference = now or datetime.now(UTC)

        if reference - last_seen > five_minutes:
            return DeviceHealth.STALE, last_seen
        return DeviceHealth.HEALTHY, last_seen