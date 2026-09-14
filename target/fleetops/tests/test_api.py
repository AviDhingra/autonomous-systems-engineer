from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from target.fleetops.app.database import get_session
from target.fleetops.app.main import create_app
from target.fleetops.app.models.db import Base

@pytest.fixture()
def client(tmp_path: Path) -> Iterator[TestClient]:
    database_path = tmp_path / "api-test.db"
    test_engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False},
    )
    TestSessionFactory = sessionmaker(
        bind=test_engine,
        class_=Session,
        autoflush=False,
        expire_on_commit=False,
    )
    Base.metadata.create_all(test_engine)

    def override_get_session() -> Iterator[Session]:
        with TestSessionFactory() as session:
            yield session

    test_app = create_app(initialize_schema=False)
    test_app.dependency_overrides[get_session] = override_get_session

    with TestClient(test_app) as test_client:
        yield test_client

    test_app.dependency_overrides.clear()
    test_engine.dispose()


def test_create_get_and_patch_device(client: TestClient) -> None:
    created_response = client.post(
        "/devices",
        json={
            "external_id": "robot-001",
            "firmware_version": "1.4.0",
            "display_name": "Sorter A",
        },
    )
    assert created_response.status_code == 201
    created = created_response.json()

    patched_response = client.patch(
        f"/devices/{created['id']}",
        json={"firmware_version": "1.5.0"},
    )
    assert patched_response.status_code == 200
    patched = patched_response.json()
    assert patched["firmware_version"] == "1.5.0"
    assert patched["display_name"] == "Sorter A"


def test_invalid_battery_is_rejected_at_http_boundary(client: TestClient) -> None:
    created = client.post(
        "/devices",
        json={"external_id": "robot-001", "firmware_version": "1.4.0"},
    ).json()

    response = client.post(
        f"/devices/{created['id']}/telemetry",
        json={
            "request_id": "req-1",
            "recorded_at": "2026-09-05T12:00:00Z",
            "temperature_c": 35.0,
            "battery_pct": -1,
        },
    )

    assert response.status_code == 422