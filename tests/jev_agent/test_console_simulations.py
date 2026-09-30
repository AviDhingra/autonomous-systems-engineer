"""Milestone 6 group 4: pages, starting and resuming simulated runs, and
the view models behind the stepper, decision nodes, dashboard and tour."""

import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jev_agent import runner as runner_module
from jev_agent.console.app import create_app
from jev_agent.console.view_models import (
    ACTORS,
    EVENT_ACTORS,
    dashboard_stats,
    decision_view,
    job_list_item,
    pipeline_steps,
    tour_steps,
)
from jev_agent.models import (
    Budget,
    Checkpoint,
    CheckpointPhase,
    EventType,
    HistoryEvent,
    Job,
    JobStatus,
    Judgment,
    Retryability,
    StepName,
)
from jev_agent.simulation import INSTANT, SCENARIO, STORIES
from jev_agent.store import JobStore


def _retryable(state: dict[str, object]) -> Judgment:
    return Judgment(retryability=Retryability.RETRYABLE, confidence=0.9)


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'sim_console.db'}"


@pytest.fixture
def store(db_url: str) -> JobStore:
    return JobStore(db_url)


@pytest.fixture
def client(db_url: str, store: JobStore, tmp_path: Path) -> TestClient:
    app = create_app(
        db_url,
        pacing=INSTANT,
        judge_fn=_retryable,
        sandbox_root=tmp_path / "sandboxes",
        background=False,
    )
    return TestClient(app, follow_redirects=False)


def _start(client: TestClient, story: str) -> str:
    response = client.post(
        "/simulations",
        content=f"story={story}",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 303, response.text
    location = response.headers["location"]
    assert location.endswith("?notice=started")
    return location.removeprefix("/jobs/").removesuffix("?notice=started")


# --- Pages ---------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/", "/how-it-works", "/tour", "/jobs", "/escalations"])
def test_pages_render_when_empty(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 200


def test_overview_explains_purpose_and_offers_every_story(client: TestClient) -> None:
    text = client.get("/").text

    assert "Deterministic Python policy decides" in text
    for story in STORIES:
        assert f'value="{story.name}"' in text
    assert "No jobs yet" in text


def test_overview_stats_reflect_jobs(client: TestClient) -> None:
    _start(client, "happy-path")
    _start(client, "retry-budget")

    text = client.get("/").text

    assert "Happy path" in text
    assert "Retry budget runs out" in text
    assert "No jobs yet" not in text


def test_how_it_works_names_every_actor(client: TestClient) -> None:
    text = client.get("/how-it-works").text

    for actor in ACTORS.values():
        assert actor.label in text


def test_tour_links_latest_run_of_a_story(client: TestClient) -> None:
    before = client.get("/tour").text
    job_id = _start(client, "crash-resume")

    after = client.get("/tour").text

    assert "See the latest run" not in before
    assert f"/jobs/{job_id}" in after


def test_banner_shows_only_without_jev_key(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    assert "JEV is not configured" in client.get("/").text

    monkeypatch.setenv("TYPESAFE_API_KEY", "x")
    assert "JEV is not configured" not in client.get("/").text


def test_jobs_filters(client: TestClient, store: JobStore) -> None:
    happy = _start(client, "happy-path")
    failed = _start(client, "step-failure")
    real = store.create_job(SCENARIO).id

    def ids(query: str) -> set[str]:
        text = client.get(f"/jobs{query}").text
        return {job_id for job_id in (happy, failed, real) if f"/jobs/{job_id}" in text}

    assert ids("") == {happy, failed, real}
    assert ids("?status=failed") == {failed}
    assert ids("?kind=simulated") == {happy, failed}
    assert ids("?kind=real") == {real}
    assert ids("?story=happy-path") == {happy}
    assert ids(f"?q={real[:8]}") == {real}
    assert ids("?status=bogus&kind=bogus") == {happy, failed, real}
    assert "No jobs match" in client.get("/jobs?story=jev-stop").text


# --- Starting simulated runs ----------------------------------------------------


def test_start_runs_story_and_redirects_to_tagged_job(client: TestClient, store: JobStore) -> None:
    job_id = _start(client, "happy-path")

    job = store.get_job(job_id)
    assert job is not None
    assert job.simulation == "happy-path"
    assert job.status is JobStatus.SUCCEEDED
    page = client.get(f"/jobs/{job_id}?notice=started").text
    assert "Simulated" in page
    assert "Simulated run started" in page


def test_start_unknown_story_is_422_and_creates_nothing(
    client: TestClient, store: JobStore
) -> None:
    response = client.post(
        "/simulations",
        content="story=nope",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 422
    assert "no story called" in response.text
    assert store.list_jobs() == []


def test_second_start_while_live_is_409(db_url: str, store: JobStore, tmp_path: Path) -> None:
    release = threading.Event()

    def blocking_judge(state: dict[str, object]) -> Judgment:
        release.wait(timeout=10)
        return _retryable(state)

    app = create_app(
        db_url, pacing=INSTANT, judge_fn=blocking_judge, sandbox_root=tmp_path / "sandboxes"
    )
    client = TestClient(app, follow_redirects=False)
    try:
        first = _start(client, "retry-then-pass")
        response = client.post(
            "/simulations",
            content="story=happy-path",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        assert response.status_code == 409
        assert "Only one runs at a time" in response.text
        assert [job.id for job in store.list_jobs()] == [first]
        assert "disabled" in client.get("/").text
    finally:
        release.set()
        app.state.simulations.wait(timeout=10)


# --- Resume ---------------------------------------------------------------------


def test_crash_story_shows_interrupted_and_resumes(client: TestClient, store: JobStore) -> None:
    job_id = _start(client, "crash-resume")

    page = client.get(f"/jobs/{job_id}").text
    assert "Interrupted" in page
    assert f'action="/jobs/{job_id}/resume"' in page
    assert "pipe-interrupted" in page
    assert "hx-get" not in page  # nothing will change until Resume

    response = client.post(f"/jobs/{job_id}/resume")

    assert response.status_code == 303
    assert response.headers["location"] == f"/jobs/{job_id}?notice=resumed"
    job = store.get_job(job_id)
    assert job is not None
    assert job.status is JobStatus.SUCCEEDED
    page = client.get(f"/jobs/{job_id}").text
    assert "resumed after interruption" in page
    assert f"/jobs/{job_id}/resume" not in page


def test_resume_refuses_real_and_finished_jobs(client: TestClient, store: JobStore) -> None:
    real = store.create_job(SCENARIO)
    store.update_job_status(real.id, JobStatus.RUNNING)
    finished = _start(client, "happy-path")

    real_response = client.post(f"/jobs/{real.id}/resume")
    finished_response = client.post(f"/jobs/{finished}/resume")

    assert real_response.status_code == 409
    assert "real" in real_response.text
    assert finished_response.status_code == 409
    assert store.get_job(real.id).status is JobStatus.RUNNING  # type: ignore[union-attr]
    assert client.post("/jobs/missing/resume").status_code == 404


def test_console_never_reaches_project1(
    client: TestClient, store: JobStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def forbidden(*args: object) -> object:
        calls.append("project1")
        raise AssertionError("the console must never call Project 1")

    monkeypatch.setattr(runner_module, "propose_fix", forbidden)
    monkeypatch.setattr(runner_module, "apply_fix", forbidden)

    for story in STORIES:
        job_id = _start(client, story.name)
        if story.name == "crash-resume":
            client.post(f"/jobs/{job_id}/resume")
    for job in store.list_jobs():
        for suffix in ("", "/status", "/history"):
            client.get(f"/jobs/{job.id}{suffix}")
    for path in ("/", "/how-it-works", "/tour", "/jobs", "/escalations"):
        client.get(path)

    assert calls == []


# --- Stepper and decision nodes on the job page ----------------------------------


def test_retry_story_shows_decision_node(client: TestClient) -> None:
    job_id = _start(client, "retry-then-pass")

    text = client.get(f"/jobs/{job_id}/status").text

    assert text.count('class="track"') == 2
    assert "JEV: retryable (90% confidence)" in text
    assert "Policy: Retry" in text
    assert "0 of 2 retries used" in text


def test_budget_story_decision_says_budget_overrode_jev(client: TestClient) -> None:
    job_id = _start(client, "retry-budget")

    text = client.get(f"/jobs/{job_id}/status").text

    assert "Policy: Escalate (Retry budget exhausted)" in text
    assert "regardless of JEV" in text


# --- View models ----------------------------------------------------------------

T0 = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


def _cp(
    step: StepName, phase: CheckpointPhase, state: dict[str, object] | None = None
) -> Checkpoint:
    return Checkpoint(id=1, job_id="j", step=step, phase=phase, state=state or {})


def _event(event_type: EventType, payload: dict[str, object], seconds: float = 5) -> HistoryEvent:
    return HistoryEvent(
        id=1,
        job_id="j",
        attempt=1,
        event_type=event_type,
        payload=payload,
        created_at=T0 + timedelta(seconds=seconds),
    )


def _job(status: JobStatus = JobStatus.RUNNING, simulation: str | None = None) -> Job:
    return Job(
        id="j" * 8,
        scenario=SCENARIO,
        status=status,
        created_at=T0,
        updated_at=T0,
        budget=Budget(max_retries=2, max_wall_clock_seconds=60.0),
        simulation=simulation,
    )


def test_every_event_type_has_an_actor() -> None:
    assert set(EVENT_ACTORS) == {event_type.value for event_type in EventType}
    assert set(EVENT_ACTORS.values()) <= set(ACTORS)


def test_pipeline_shows_unreached_steps_as_pending() -> None:
    steps = pipeline_steps([_cp(StepName.PROPOSE, CheckpointPhase.BEFORE)], "running")

    assert [(s.name, s.state) for s in steps] == [
        ("propose", "running"),
        ("apply", "pending"),
        ("verify", "pending"),
    ]
    assert steps[0].actor.key == "model"
    assert steps[1].actor.key == "python"


def test_pipeline_interrupted_and_failed_states() -> None:
    checkpoints = [
        _cp(StepName.PROPOSE, CheckpointPhase.BEFORE),
        _cp(StepName.PROPOSE, CheckpointPhase.AFTER, {"file_path": "a.py"}),
        _cp(StepName.APPLY, CheckpointPhase.BEFORE),
    ]

    interrupted = pipeline_steps(checkpoints, "interrupted")
    raised = pipeline_steps(checkpoints, "failed")

    assert [s.state for s in interrupted] == ["done", "interrupted", "pending"]
    assert [s.state for s in raised] == ["done", "failed", "pending"]


def test_pipeline_failed_verify_blocks_nothing_after_it() -> None:
    steps = pipeline_steps(
        [
            _cp(StepName.PROPOSE, CheckpointPhase.AFTER, {"file_path": "a.py"}),
            _cp(StepName.APPLY, CheckpointPhase.AFTER, {"file_path": "a.py"}),
            _cp(StepName.VERIFY, CheckpointPhase.AFTER, {"passed": False, "checks": []}),
        ],
        "running",
    )

    assert [s.state for s in steps] == ["done", "done", "failed"]


def test_decision_view_none_without_judgment() -> None:
    assert decision_view(_job(), 1, [_event(EventType.ROLLBACK, {})]) is None


@pytest.mark.parametrize(
    ("output", "outcome", "reason", "expected"),
    [
        ({"retryability": "retryable", "confidence": 0.9}, "retry", None, "judged the failure"),
        ({"error": "RuntimeError: down"}, "retry", None, "fixed rule"),
        ({"retryability": "not_retryable", "confidence": 0.3}, "retry", None, "below policy"),
        (
            {"retryability": "not_retryable", "confidence": 0.9},
            "escalate",
            "jev_not_retryable",
            "instead of guessing",
        ),
        (
            {"retryability": "retryable", "confidence": 0.9},
            "escalate",
            "retry_budget_exhausted",
            "retry budget was spent",
        ),
        (
            {"retryability": "retryable", "confidence": 0.9},
            "escalate",
            "wall_clock_exceeded",
            "time budget was spent",
        ),
    ],
)
def test_decision_view_explains_policy(
    output: dict[str, object], outcome: str, reason: str | None, expected: str
) -> None:
    events = [_event(EventType.JEV_JUDGMENT, {"input": {}, "output": output, "outcome": outcome})]
    if reason:
        events.append(_event(EventType.ESCALATION, {"reason": reason, "context": {}}))

    view = decision_view(_job(), 1, events)

    assert view is not None
    assert expected in view.explanation
    assert view.retries == "0 of 2 retries used"
    assert view.elapsed == "5s of 1m 0s used"
    if "error" in output:
        assert view.judgment is None
        assert view.jev_error == "RuntimeError: down"


def test_dashboard_stats_counts() -> None:
    jobs = [
        _job(JobStatus.SUCCEEDED, "happy-path"),
        _job(JobStatus.SUCCEEDED),
        _job(JobStatus.WAITING_ON_ESCALATION, "retry-budget"),
        _job(JobStatus.RUNNING, "crash-resume"),
    ]

    stats = dashboard_stats(jobs, pending_escalations=1)

    assert (stats.total, stats.succeeded, stats.waiting, stats.active) == (4, 2, 1, 1)
    assert stats.simulated == 3
    assert stats.success_rate_label == "67%"
    assert {s.status for s in stats.breakdown} == {
        JobStatus.SUCCEEDED,
        JobStatus.WAITING_ON_ESCALATION,
        JobStatus.RUNNING,
    }
    assert dashboard_stats([], 0).success_rate_label == "–"


def test_job_list_item_marks_interrupted_and_story() -> None:
    item = job_list_item(
        _job(JobStatus.RUNNING, "crash-resume"), T0, True, {"crash-resume": "Crash and resume"}
    )

    assert (item.label, item.badge) == ("Interrupted", "badge-interrupted")
    assert item.story_title == "Crash and resume"
    real = job_list_item(_job(JobStatus.SUCCEEDED), T0, False, {})
    assert real.story_title is None
    assert real.label == "Succeeded"


def test_tour_steps_cover_real_stories() -> None:
    names = {story.name for story in STORIES}

    steps = tour_steps(lambda story: None)

    assert len(steps) == 6
    assert all(step.story_name in names for step in steps if step.story_name)
    assert steps[-1].story_name is None
