"""Milestone 6: simulated stories drive the real runner with fake steps."""

import subprocess
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from jev_agent import judgment as judgment_module
from jev_agent.models import (
    CheckpointPhase,
    EscalationReason,
    EventType,
    Job,
    JobStatus,
    Judgment,
    Retryability,
    StepName,
)
from jev_agent.simulation import (
    INSTANT,
    SCENARIO,
    STORIES,
    NotResumable,
    SimulatedCrash,
    SimulationBusy,
    SimulationRunner,
    get_story,
    intended_judge,
    jev_configured,
    run_story,
)
from jev_agent.store import JobStore


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    return JobStore(f"sqlite:///{tmp_path / 'simulation_test.db'}")


def _an_hour_later() -> datetime:
    return datetime.now(UTC) + timedelta(hours=1)


def _run(store: JobStore, tmp_path: Path, name: str, **kwargs: object) -> Job:
    story = get_story(name)
    job = store.create_job(SCENARIO, story.budget, simulation=story.name)
    kwargs.setdefault("judge_fn", intended_judge(story))
    return run_story(
        store,
        story,
        job.id,
        pacing=INSTANT,
        sandbox_root=tmp_path / "sandboxes",
        **kwargs,  # type: ignore[arg-type]
    )


def _after_checkpoints(store: JobStore, job_id: str, step: StepName) -> int:
    return sum(
        1
        for c in store.list_checkpoints(job_id)
        if c.step is step and c.phase is CheckpointPhase.AFTER
    )


def _reasons(store: JobStore, job_id: str) -> list[EscalationReason]:
    return [e.reason for e in store.list_escalations(job_id)]


def test_story_names_are_unique_and_complete() -> None:
    names = [story.name for story in STORIES]

    assert len(names) == len(set(names))
    assert set(names) == {
        "happy-path",
        "crash-resume",
        "retry-then-pass",
        "jev-stop",
        "retry-budget",
        "wall-clock-budget",
        "step-failure",
    }
    for story in STORIES:
        assert story.title and story.summary and story.pattern


def test_unknown_story_raises() -> None:
    with pytest.raises(KeyError):
        get_story("no-such-story")


def test_happy_path_succeeds_first_time(store: JobStore, tmp_path: Path) -> None:
    job = _run(store, tmp_path, "happy-path")

    assert job.status is JobStatus.SUCCEEDED
    assert job.retry_count == 0
    assert job.simulation == "happy-path"


def test_crash_resume_leaves_job_interrupted_then_resumes_at_verify(
    store: JobStore, tmp_path: Path
) -> None:
    story = get_story("crash-resume")
    job = store.create_job(SCENARIO, story.budget, simulation=story.name)
    sandboxes = tmp_path / "sandboxes"

    with pytest.raises(SimulatedCrash):
        run_story(store, story, job.id, pacing=INSTANT, sandbox_root=sandboxes)
    interrupted = store.get_job(job.id)
    assert interrupted is not None
    assert interrupted.status is JobStatus.RUNNING

    resumed = run_story(store, story, job.id, pacing=INSTANT, sandbox_root=sandboxes)

    assert resumed.status is JobStatus.SUCCEEDED
    assert _after_checkpoints(store, job.id, StepName.PROPOSE) == 1
    assert _after_checkpoints(store, job.id, StepName.APPLY) == 1
    verify_starts = [
        c
        for c in store.list_checkpoints(job.id)
        if c.step is StepName.VERIFY and c.phase is CheckpointPhase.BEFORE
    ]
    assert len(verify_starts) == 2


def test_retry_then_pass_rolls_back_and_passes(store: JobStore, tmp_path: Path) -> None:
    job = _run(store, tmp_path, "retry-then-pass")

    assert job.status is JobStatus.SUCCEEDED
    assert job.retry_count == 1
    events = {e.event_type for e in store.list_history(job.id)}
    assert {EventType.JEV_JUDGMENT, EventType.ROLLBACK, EventType.RETRY} <= events


def test_jev_stop_escalates_on_confident_not_retryable(store: JobStore, tmp_path: Path) -> None:
    job = _run(store, tmp_path, "jev-stop")

    assert job.status is JobStatus.WAITING_ON_ESCALATION
    assert _reasons(store, job.id) == [EscalationReason.JEV_NOT_RETRYABLE]


def test_retry_budget_escalates(store: JobStore, tmp_path: Path) -> None:
    job = _run(store, tmp_path, "retry-budget")

    assert job.status is JobStatus.WAITING_ON_ESCALATION
    assert job.retry_count == 1
    assert _reasons(store, job.id) == [EscalationReason.RETRY_BUDGET_EXHAUSTED]


def test_wall_clock_budget_escalates(store: JobStore, tmp_path: Path) -> None:
    job = _run(store, tmp_path, "wall-clock-budget", clock=_an_hour_later)

    assert job.status is JobStatus.WAITING_ON_ESCALATION
    assert _reasons(store, job.id) == [EscalationReason.WALL_CLOCK_EXCEEDED]


def test_step_failure_ends_failed(store: JobStore, tmp_path: Path) -> None:
    job = _run(store, tmp_path, "step-failure")

    assert job.status is JobStatus.FAILED
    errors = [e for e in store.list_history(job.id) if e.event_type is EventType.STEP_ERROR]
    assert len(errors) == 1
    assert errors[0].payload["step"] == "propose"


def test_verify_failures_carry_realistic_output(store: JobStore, tmp_path: Path) -> None:
    job = _run(store, tmp_path, "jev-stop")

    judgment = next(e for e in store.list_history(job.id) if e.event_type is EventType.JEV_JUDGMENT)
    state = judgment.payload["input"]
    assert isinstance(state, dict)
    assert "FLEETOPS_DATABASE_URL" in str(state["failure_output"])


def test_raising_judge_follows_fixed_rule_fallback(store: JobStore, tmp_path: Path) -> None:
    def unavailable(state: dict[str, object]) -> Judgment:
        raise RuntimeError("JEV unavailable")

    job = _run(store, tmp_path, "jev-stop", judge_fn=unavailable)

    # Without a judgment, policy retries while under budget, then escalates.
    assert job.status is JobStatus.WAITING_ON_ESCALATION
    assert _reasons(store, job.id) == [EscalationReason.RETRY_BUDGET_EXHAUSTED]
    outputs = [
        e.payload["output"]
        for e in store.list_history(job.id)
        if e.event_type is EventType.JEV_JUDGMENT
    ]
    assert outputs and all(o == {"error": "RuntimeError: JEV unavailable"} for o in outputs)


def test_no_judge_fn_uses_the_real_jev_judgment(
    store: JobStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, object]] = []

    def real_judge_stand_in(state: dict[str, object]) -> Judgment:
        calls.append(state)
        return Judgment(retryability=Retryability.RETRYABLE, confidence=0.8)

    # `run_job` resolves its default judge at call time; patching the real
    # function proves a simulated run with no judge_fn reaches it.
    monkeypatch.setattr(judgment_module, "judge_verify_failure", real_judge_stand_in)

    job = _run(store, tmp_path, "retry-then-pass", judge_fn=None)

    assert job.status is JobStatus.SUCCEEDED
    assert len(calls) == 1


def test_sandbox_is_outside_the_repo_and_fleetops_untouched(
    store: JobStore, tmp_path: Path
) -> None:
    job = _run(store, tmp_path, "retry-then-pass")

    sandbox_file = tmp_path / "sandboxes" / job.id / "app" / "services" / "device_service.py"
    assert sandbox_file.exists()
    status = subprocess.run(
        ["git", "status", "--porcelain", "--", "target/fleetops"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert status.stdout.strip() == ""


def test_jev_configured_reads_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    assert not jev_configured()

    monkeypatch.setenv("TYPESAFE_API_KEY", "x")
    assert jev_configured()


# --- SimulationRunner --------------------------------------------------------


def _runner(store: JobStore, tmp_path: Path, **kwargs: object) -> SimulationRunner:
    return SimulationRunner(
        store,
        pacing=INSTANT,
        sandbox_root=tmp_path / "sandboxes",
        **kwargs,  # type: ignore[arg-type]
    )


def test_runner_start_runs_story_and_tags_job(store: JobStore, tmp_path: Path) -> None:
    runner = _runner(store, tmp_path, judge_fn=intended_judge(get_story("happy-path")))

    job = runner.start("happy-path")
    runner.wait(timeout=10)

    finished = store.get_job(job.id)
    assert finished is not None
    assert finished.status is JobStatus.SUCCEEDED
    assert finished.simulation == "happy-path"
    assert runner.live_job_id is None


def test_runner_refuses_a_second_run_while_one_is_live(store: JobStore, tmp_path: Path) -> None:
    release = threading.Event()

    def blocking_judge(state: dict[str, object]) -> Judgment:
        release.wait(timeout=10)
        return Judgment(retryability=Retryability.RETRYABLE, confidence=0.9)

    runner = _runner(store, tmp_path, judge_fn=blocking_judge)
    first = runner.start("retry-then-pass")
    try:
        with pytest.raises(SimulationBusy):
            runner.start("happy-path")
        assert [job.id for job in store.list_jobs()] == [first.id]
        assert runner.live_job_id == first.id
        assert not runner.is_interrupted(store.get_job(first.id))  # type: ignore[arg-type]
    finally:
        release.set()
        runner.wait(timeout=10)

    assert store.get_job(first.id).status is JobStatus.SUCCEEDED  # type: ignore[union-attr]


def test_runner_crash_leaves_job_resumable_then_resume_succeeds(
    store: JobStore, tmp_path: Path
) -> None:
    runner = _runner(store, tmp_path, background=False)

    job = runner.start("crash-resume")
    interrupted = store.get_job(job.id)
    assert interrupted is not None
    assert runner.live_job_id is None
    assert runner.is_interrupted(interrupted)

    runner.resume(job.id)

    resumed = store.get_job(job.id)
    assert resumed is not None
    assert resumed.status is JobStatus.SUCCEEDED
    assert not runner.is_interrupted(resumed)


def test_runner_resume_refuses_real_finished_and_unknown_jobs(
    store: JobStore, tmp_path: Path
) -> None:
    runner = _runner(store, tmp_path, background=False)
    real = store.create_job(SCENARIO)
    store.update_job_status(real.id, JobStatus.RUNNING)
    finished = runner.start("happy-path")

    with pytest.raises(NotResumable):
        runner.resume(real.id)
    with pytest.raises(NotResumable):
        runner.resume(finished.id)
    with pytest.raises(KeyError):
        runner.resume("missing")
    assert store.get_job(real.id).status is JobStatus.RUNNING  # type: ignore[union-attr]


def test_runner_unknown_story_creates_no_job(store: JobStore, tmp_path: Path) -> None:
    runner = _runner(store, tmp_path, background=False)

    with pytest.raises(KeyError):
        runner.start("no-such-story")
    assert store.list_jobs() == []
