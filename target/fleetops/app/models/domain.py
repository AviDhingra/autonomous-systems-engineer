from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class DeviceHealth(StrEnum):
    HEALTHY = "healthy"
    STALE = "stale"
    UNKNOWN = "unknown"


class IncidentSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class Device:
    id: str
    external_id: str
    firmware_version: str
    display_name: str | None = None


@dataclass(frozen=True, slots=True)
class Telemetry:
    id: str
    device_id: str
    request_id: str
    recorded_at: datetime
    temperature_c: float
    battery_pct: float