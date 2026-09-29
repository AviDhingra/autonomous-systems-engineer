from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jev_agent.console.app import create_app
from jev_agent.models import (
    Budget,
    CheckpointPhase,
    EscalationReason,
    EventType,
    JobStatus,
    StepName,
)
from jev_agent.store import JobStore


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'console_test.db'}"


@pytest.fixture
def store(db_url: str) -> JobStore:
    return JobStore(db_url)


@pytest.fixture
def client(db_url: str, store: JobStore) -> TestClient:
    # `store` first so the schema exists; the app opens the same file.
    return TestClient(create_app(db_url), follow_redirects=False)


def _escalated(store: JobStore, scenario: str = "S02-unsupported-patch-fields"):  # type: ignore[no-untyped-def]
    job = store.create_job(scenario, Budget(max_retries=1, max_wall_clock_seconds=600.0))
    store.add_checkpoint(job.id, StepName.PROPOSE, CheckpointPhase.BEFORE, attempt=1)
    store.add_checkpoint(job.id, StepName.PROPOSE, CheckpointPhase.AFTER, attempt=1)
    store.increment_retry_count(job.id, reason="verify failed")
    context: dict[str, object] = {
        "retry_count": 1,
        "max_retries": 1,
        "elapsed_seconds": 12.0,
        "max_wall_clock_seconds": 600.0,
        "judgment": None,
        "failure_output": "boom",
    }
    escalation = store.escalate(job.id, 1, EscalationReason.RETRY_BUDGET_EXHAUSTED, context)
    return job, escalation


def test_job_list_empty_state(client: TestClient) -> None:
    response = client.get("/jobs")

    assert response.status_code == 200
    assert "No jobs yet" in response.text


def test_job_list_shows_every_job_and_status(client: TestClient, store: JobStore) -> None:
    done = store.create_job("S-done")
    store.update_job_status(done.id, JobStatus.SUCCEEDED)
    waiting, _ = _escalated(store, "S-waiting")

    response = client.get("/jobs")

    assert response.status_code == 200
    assert "S-done" in response.text
    assert "S-waiting" in response.text
    assert "Succeeded" in response.text
    assert "Waiting on escalation" in response.text
    assert f"/jobs/{waiting.id}" in response.text


def test_job_detail_shows_checkpoints_budget_escalation_and_history(
    client: TestClient, store: JobStore
) -> None:
    job, escalation = _escalated(store)

    response = client.get(f"/jobs/{job.id}")

    assert response.status_code == 200
    assert "Attempt 1" in response.text
    assert 'step-name">propose' in response.text
    assert "1 / 1" in response.text  # retries used / max
    assert "Retry budget exhausted" in response.text
    assert "boom" in response.text  # failure output behind the escalation
    assert f"/escalations/{escalation.id}/resolve" in response.text
    assert "Escalated: retry_budget_exhausted" in response.text


def test_status_and_history_fragments(client: TestClient, store: JobStore) -> None:
    job, _ = _escalated(store)

    status = client.get(f"/jobs/{job.id}/status")
    history = client.get(f"/jobs/{job.id}/history")

    assert status.status_code == 200
    assert "Waiting on escalation" in status.text
    assert "<html" not in status.text
    assert history.status_code == 200
    assert "Execution history" in history.text
    assert "<html" not in history.text


def test_history_is_chronological(client: TestClient, store: JobStore) -> None:
    job, _ = _escalated(store)
    store.append_history_event(job.id, 1, EventType.ROLLBACK, {"file_path": "zzz.py"})

    text = client.get(f"/jobs/{job.id}/history").text

    assert text.index("Escalated:") < text.index("zzz.py")


def test_pending_escalations_page(client: TestClient, store: JobStore) -> None:
    job, escalation = _escalated(store)
    resolved_job, resolved = _escalated(store, "S-other")
    store.resolve_escalation(resolved.id, "handled it")

    response = client.get("/escalations")

    assert response.status_code == 200
    pending_part, resolved_part = response.text.split("<h2>Resolved</h2>")
    assert f"#{escalation.id}" in pending_part
    assert f"#{resolved.id}" not in pending_part
    assert "boom" in pending_part
    assert f"#{resolved.id}" in resolved_part
    assert "handled it" in resolved_part
    assert f"/jobs/{job.id}" in pending_part
    assert resolved_job.id[:8] in resolved_part


def test_escalations_page_empty_state(client: TestClient) -> None:
    response = client.get("/escalations")

    assert response.status_code == 200
    assert "No pending escalations" in response.text


def test_resolve_records_and_redirects_and_leaves_job_waiting(
    client: TestClient, store: JobStore
) -> None:
    job, escalation = _escalated(store)

    response = client.post(
        f"/escalations/{escalation.id}/resolve",
        content="note=looked+into+it",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/jobs/{job.id}?notice=resolved"
    resolved = store.get_escalation(escalation.id)
    assert resolved is not None
    assert resolved.resolution_note == "looked into it"
    assert store.get_job(job.id).status is JobStatus.WAITING_ON_ESCALATION  # type: ignore[union-attr]
    events = [
        e for e in store.list_history(job.id) if e.event_type is EventType.ESCALATION_RESOLVED
    ]
    assert len(events) == 1
    assert store.list_pending_escalations() == []


def test_resolve_without_body_and_twice_is_harmless(client: TestClient, store: JobStore) -> None:
    job, escalation = _escalated(store)

    first = client.post(f"/escalations/{escalation.id}/resolve")
    second = client.post(f"/escalations/{escalation.id}/resolve")

    assert first.status_code == second.status_code == 303
    events = [
        e for e in store.list_history(job.id) if e.event_type is EventType.ESCALATION_RESOLVED
    ]
    assert len(events) == 1


@pytest.mark.parametrize(
    "path", ["/jobs/missing", "/jobs/missing/status", "/jobs/missing/history", "/nope"]
)
def test_unknown_pages_404(client: TestClient, path: str) -> None:
    response = client.get(path)

    assert response.status_code == 404
    assert "Not found" in response.text


def test_resolve_unknown_escalation_404(client: TestClient) -> None:
    response = client.post("/escalations/999/resolve")

    assert response.status_code == 404


def test_elapsed_uses_injected_clock(db_url: str, store: JobStore) -> None:
    job = store.create_job("S-running")
    store.update_job_status(job.id, JobStatus.RUNNING)
    later = datetime.now(UTC) + timedelta(seconds=125)
    client = TestClient(create_app(db_url, clock=lambda: later))

    response = client.get(f"/jobs/{job.id}/status")

    assert "2m " in response.text
