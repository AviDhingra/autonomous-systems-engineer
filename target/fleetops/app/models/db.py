from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, DateTime, Float, UniqueConstraint
from datetime import datetime


class Base(DeclarativeBase):
    pass

class DeviceRow(Base):
    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    external_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    firmware_version: Mapped[str] = mapped_column(String(40))
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)


class TelemetryRow(Base):
    __tablename__ = "telemetry"
    __table_args__ = (
        UniqueConstraint(
            "device_id",
            "request_id",
            name="uq_telemetry_device_request",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    device_id: Mapped[str] = mapped_column(String(36), index=True)
    request_id: Mapped[str] = mapped_column(String(100))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    temperature_c: Mapped[float] = mapped_column(Float)
    battery_pct: Mapped[float] = mapped_column(Float)
