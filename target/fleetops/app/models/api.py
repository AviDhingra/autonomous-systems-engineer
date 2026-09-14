from datetime import datetime
from pydantic import BaseModel, Field
from .domain import DeviceHealth

class DeviceCreate(BaseModel):
    external_id: str = Field(min_length=1, max_length=100)
    firmware_version: str = Field(min_length=1, max_length=40)
    display_name: str | None = Field(default=None, max_length=120)


class DevicePatch(BaseModel):
    firmware_version: str | None = Field(default=None, min_length=1, max_length=40)
    display_name: str | None = Field(default=None, max_length=120)


class DeviceResponse(BaseModel):
    id: str
    external_id: str
    firmware_version: str
    display_name: str | None


class TelemetryCreate(BaseModel):
    request_id: str = Field(min_length=1, max_length=100)
    recorded_at: datetime
    temperature_c: float
    battery_pct: float = Field(ge=0, le=100)


class TelemetryResponse(BaseModel):
    id: str
    device_id: str
    request_id: str
    recorded_at: datetime
    temperature_c: float
    battery_pct: float


class DeviceHealthResponse(BaseModel):
    device_id: str
    health: DeviceHealth
    last_seen_at: datetime | None