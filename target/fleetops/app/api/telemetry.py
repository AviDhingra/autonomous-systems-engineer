from fastapi import APIRouter, Depends, HTTPException, Query, status
from ..models.api import DeviceHealthResponse, TelemetryCreate, TelemetryResponse
from ..services.errors import DeviceNotFoundError
from ..services.telemetry import TelemetryService
from .dependencies import get_telemetry_service


router = APIRouter(prefix="/devices/{device_id}", tags=["telemetry"])


@router.post("/telemetry", response_model=TelemetryResponse, status_code=status.HTTP_201_CREATED)
def ingest_telemetry(
    device_id: str,
    request: TelemetryCreate,
    service: TelemetryService = Depends(get_telemetry_service),
) -> TelemetryResponse:
    try:
        record = service.ingest(
            device_id,
            request_id=request.request_id,
            recorded_at=request.recorded_at,
            temperature_c=request.temperature_c,
            battery_pct=request.battery_pct,
        )
    except DeviceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return TelemetryResponse.model_validate(record, from_attributes=True)


@router.get("/telemetry", response_model=list[TelemetryResponse])
def list_telemetry(
    device_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    service: TelemetryService = Depends(get_telemetry_service),
) -> list[TelemetryResponse]:
    try:
        records = service.list_for_device(device_id, limit=limit)
    except DeviceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [TelemetryResponse.model_validate(record, from_attributes=True) for record in records]


@router.get("/health", response_model=DeviceHealthResponse)
def get_health(
    device_id: str,
    service: TelemetryService = Depends(get_telemetry_service),
) -> DeviceHealthResponse:
    try:
        health, last_seen = service.health(device_id)
    except DeviceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return DeviceHealthResponse(device_id=device_id, health=health, last_seen_at=last_seen)