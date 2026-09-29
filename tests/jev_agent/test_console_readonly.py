"""The console writes only by resolving escalations and starting or resuming
simulated runs; every page view leaves the store unchanged."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jev_agent.console.app import create_app
from jev_agent.demo_console_seed import seed_demo
from jev_agent.models import EscalationReason, JobStatus
from jev_agent.store import JobStore


def test_only_write_routes_are_resolve_start_and_resume(tmp_path: Path) -> None:
    app = create_app(f"sqlite:///{tmp_path / 'ro_routes.db'}")

    # OpenAPI lists every operation, including routes from included routers.
    non_get = {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
        if method.lower() != "get"
    }

    assert non_get == {
        ("POST", "/escalations/{escalation_id}/resolve"),
        ("POST", "/simulations"),
        ("POST", "/jobs/{job_id}/resume"),
    }


def _counts(store: JobStore) -> tuple[int, int, int, int, str]:
    jobs = store.list_jobs()
    return (
        len(jobs),
        sum(len(store.list_checkpoints(job.id)) for job in jobs),
        sum(len(store.list_history(job.id)) for job in jobs),
        sum(len(store.list_escalations(job.id)) for job in jobs),
        ",".join(f"{job.id}:{job.status.value}:{job.retry_count}" for job in jobs),
    )


def test_get_routes_do_not_change_the_store(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'ro_get.db'}"
    store = JobStore(url)
    job = store.create_job("S-a")
    store.update_job_status(job.id, JobStatus.RUNNING)
    escalated = store.create_job("S-b")
    store.escalate(escalated.id, 1, EscalationReason.RETRY_BUDGET_EXHAUSTED, {"k": 1})
    before = _counts(store)
    client = TestClient(create_app(url))

    paths = ["/", "/how-it-works", "/tour", "/jobs", "/escalations", "/static/console.css"]
    for job_id in (job.id, escalated.id):
        paths += [f"/jobs/{job_id}", f"/jobs/{job_id}/status", f"/jobs/{job_id}/history"]
    for path in paths:
        assert client.get(path).status_code == 200, path

    assert _counts(store) == before


def test_seeded_demo_database_is_unchanged_by_browsing(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'ro_seeded.db'}"
    store = JobStore(url)
    seed_demo(store, stand_in_judges=True, instant=True, sandbox_root=tmp_path / "sandboxes")
    before = _counts(store)
    client = TestClient(create_app(url))

    for job in store.list_jobs():
        for suffix in ("", "/status", "/history"):
            assert client.get(f"/jobs/{job.id}{suffix}").status_code == 200
    for path in ("/", "/how-it-works", "/tour", "/jobs", "/escalations"):
        assert client.get(path).status_code == 200, path

    assert _counts(store) == before


@pytest.mark.parametrize("method", ["put", "delete", "patch"])
def test_other_write_methods_are_not_allowed(tmp_path: Path, method: str) -> None:
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ro_methods.db'}"))

    for path in ("/", "/escalations", "/escalations/1/resolve", "/jobs/x"):
        assert client.request(method, path).status_code in {404, 405}
