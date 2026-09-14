from fastapi import APIRouter, Depends, HTTPException, status

from ..models.api import DeviceCreate, DevicePatch, DeviceResponse
from ..services.devices import DeviceService
from ..services.errors import DeviceNotFoundError
from .dependencies import get_device_service


router = APIRouter(prefix="/devices", tags=["devices"])


@router.post("", response_model=DeviceResponse, status_code=status.HTTP_201_CREATED)
def create_device(
    request: DeviceCreate,
    service: DeviceService = Depends(get_device_service),
) -> DeviceResponse:
    device = service.create(
        external_id=request.external_id,
        firmware_version=request.firmware_version,
        display_name=request.display_name,
    )
    return DeviceResponse.model_validate(device, from_attributes=True)

@router.get("/{device_id}", response_model=DeviceResponse)
def get_device(
    device_id: str,
    service: DeviceService = Depends(get_device_service),
) -> DeviceResponse:
    try:
        device = service.get(device_id)
    except DeviceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return DeviceResponse.model_validate(device, from_attributes=True)


@router.patch("/{device_id}", response_model=DeviceResponse)
def patch_device(
    device_id: str,
    request: DevicePatch,
    service: DeviceService = Depends(get_device_service),
) -> DeviceResponse:
    try:
        device = service.patch(
            device_id,
            changes=request.model_dump(exclude_unset=True),
        )
    except DeviceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return DeviceResponse.model_validate(device, from_attributes=True)
