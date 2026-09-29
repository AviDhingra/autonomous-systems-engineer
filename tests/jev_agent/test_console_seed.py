import subprocess
from pathlib import Path
from unittest import mock

import pytest

from jev_agent import demo_console_seed
from jev_agent.console import __main__ as console_main
from jev_agent.demo_console_seed import seed_demo
from jev_agent.models import (
    CheckpointPhase,
    EscalationReason,
    EventType,
    HistoryEvent,
    Job,
    JobStatus,
    ResolutionState,
    StepName,
)
from jev_agent.store import JobStore


@pytest.fixture(scope="module")
def seeded(tmp_path_factory: pytest.TempPathFactory) -> tuple[JobStore, dict[str, Job]]:
    store = JobStore(f"sqlite:///{tmp_path_factory.mktemp('seed') / 'seed_test.db'}")
    # The wall-clock story really sleeps; shrink it so the suite stays fast.
    with mock.patch.object(demo_console_seed, "WALL_CLOCK_SECONDS", 0.05):
        jobs = seed_demo(store)
    return store, dict(jobs)


def _job(seeded: tuple[JobStore, dict[str, Job]], name: str) -> tuple[JobStore, Job]:
    store, jobs = seeded
    return store, jobs[name]


def _events(store: JobStore, job_id: str, event_type: EventType) -> list[HistoryEvent]:
    return [e for e in store.list_history(job_id) if e.event_type is event_type]


def test_one_job_per_story_with_expected_statuses(
    seeded: tuple[JobStore, dict[str, Job]],
) -> None:
    store, jobs = seeded

    assert {name: job.status for name, job in jobs.items()} == {
        "interrupted": JobStatus.SUCCEEDED,
        "retried": JobStatus.SUCCEEDED,
        "jev-retry": JobStatus.SUCCEEDED,
        "jev-stop": JobStatus.WAITING_ON_ESCALATION,
        "retry-budget": JobStatus.WAITING_ON_ESCALATION,
        "wall-clock": JobStatus.WAITING_ON_ESCALATION,
        "resolved": JobStatus.WAITING_ON_ESCALATION,
        "failed": JobStatus.FAILED,
    }
    assert len(store.list_jobs()) == len(jobs)


def test_interrupted_job_resumed_at_verify_without_redoing_work(
    seeded: tuple[JobStore, dict[str, Job]],
) -> None:
    store, job = _job(seeded, "interrupted")

    checkpoints = store.list_checkpoints(job.id)
    proposes = [
        c for c in checkpoints if c.step is StepName.PROPOSE and c.phase is CheckpointPhase.AFTER
    ]
    applies = [
        c for c in checkpoints if c.step is StepName.APPLY and c.phase is CheckpointPhase.AFTER
    ]
    verifies_before = [
        c for c in checkpoints if c.step is StepName.VERIFY and c.phase is CheckpointPhase.BEFORE
    ]
    assert len(proposes) == 1
    assert len(applies) == 1
    assert len(verifies_before) == 2  # the interrupted run and the resumed one


def test_retried_job_records_fallback_when_jev_unavailable(
    seeded: tuple[JobStore, dict[str, Job]],
) -> None:
    store, job = _job(seeded, "retried")

    assert job.retry_count == 1
    assert len(_events(store, job.id, EventType.RETRY)) == 1
    assert len(_events(store, job.id, EventType.ROLLBACK)) == 1
    judgments = _events(store, job.id, EventType.JEV_JUDGMENT)
    assert len(judgments) == 1
    assert judgments[0].payload["output"] == {"error": "RuntimeError: JEV unavailable"}


def test_jev_stories_record_judgments_and_outcomes(
    seeded: tuple[JobStore, dict[str, Job]],
) -> None:
    store, retry_job = _job(seeded, "jev-retry")
    _, stop_job = _job(seeded, "jev-stop")

    retry_judgment = _events(store, retry_job.id, EventType.JEV_JUDGMENT)[0]
    stop_judgment = _events(store, stop_job.id, EventType.JEV_JUDGMENT)[0]
    assert retry_judgment.payload["outcome"] == "retry"
    assert stop_judgment.payload["outcome"] == "escalate"
    assert [e.reason for e in store.list_escalations(stop_job.id)] == [
        EscalationReason.JEV_NOT_RETRYABLE
    ]


def test_budget_stories_escalate_with_expected_reasons(
    seeded: tuple[JobStore, dict[str, Job]],
) -> None:
    store, retry_budget = _job(seeded, "retry-budget")
    _, wall_clock = _job(seeded, "wall-clock")

    assert [e.reason for e in store.list_escalations(retry_budget.id)] == [
        EscalationReason.RETRY_BUDGET_EXHAUSTED
    ]
    assert [e.reason for e in store.list_escalations(wall_clock.id)] == [
        EscalationReason.WALL_CLOCK_EXCEEDED
    ]


def test_pending_and_resolved_escalations_both_present(
    seeded: tuple[JobStore, dict[str, Job]],
) -> None:
    store, resolved_job = _job(seeded, "resolved")

    resolved = store.list_escalations(resolved_job.id)
    assert [e.resolution_state for e in resolved] == [ResolutionState.RESOLVED]
    assert len(store.list_pending_escalations()) == 3  # jev-stop, retry-budget, wall-clock
    assert len(store.list_resolved_escalations()) == 1


def test_failed_job_has_step_error(seeded: tuple[JobStore, dict[str, Job]]) -> None:
    store, job = _job(seeded, "failed")

    assert len(_events(store, job.id, EventType.STEP_ERROR)) == 1


def test_seed_needs_no_git_changes(seeded: tuple[JobStore, dict[str, Job]]) -> None:
    del seeded
    status = subprocess.run(
        ["git", "status", "--porcelain", "--", "target/fleetops"],
        capture_output=True,
        text=True,
        check=True,
    )

    assert status.stdout.strip() == ""


def test_seed_cli_refuses_existing_jobs_without_reset(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'cli_seed.db'}"
    JobStore(url).create_job("S")

    with pytest.raises(SystemExit) as excinfo:
        demo_console_seed.main(["--database-url", url])

    assert excinfo.value.code == 2


def test_seed_cli_reset_recreates_database(tmp_path: Path) -> None:
    db_file = tmp_path / "cli_reset.db"
    url = f"sqlite:///{db_file}"
    db_file.write_bytes(b"stale file from an older run")

    with mock.patch.object(demo_console_seed, "WALL_CLOCK_SECONDS", 0.05):
        assert demo_console_seed.main(["--database-url", url, "--reset"]) == 0

    scenarios = {job.scenario for job in JobStore(url).list_jobs()}
    assert scenarios == {demo_console_seed.SCENARIO}


def test_launcher_binds_localhost_only(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'launch.db'}"

    with mock.patch.object(console_main.uvicorn, "run") as run:
        assert console_main.main(["--database-url", url, "--port", "8123"]) == 0

    assert run.call_args.kwargs == {"host": "127.0.0.1", "port": 8123}


def test_launcher_has_no_host_option() -> None:
    with pytest.raises(SystemExit):
        console_main.main(["--host", "0.0.0.0"])
