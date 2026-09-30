"""Simulated runs: preset stories that exercise the real governance path.

Each story drives the real `run_job` (checkpoints, recovery, retries,
rollback, budgets, escalation) with fake PROPOSE, APPLY and VERIFY steps, so
no frontier model is called and `target/fleetops` is never touched. The JEV
judgment is the real one by default (`run_job`'s own default), so a story's
retry/escalate decision comes from the live JEV API and the deterministic
policy. Tests and offline use pass a `judge_fn`.

Fake steps derive everything they need from the store (which attempt this
is, whether VERIFY already started once), so a resumed story behaves exactly
like a resumed real job: nothing is kept in memory between runs.
"""

import logging
import os
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ase.models import FixProposal
from ase.verify import CheckResult, VerificationResult
from jev_agent.models import (
    DEFAULT_BUDGET,
    NON_RUNNABLE_JOB_STATUSES,
    Budget,
    CheckpointPhase,
    Job,
    JobStatus,
    Judgment,
    Retryability,
    StepName,
)
from jev_agent.runner import ClockFn, JudgeFn, run_job
from jev_agent.store import JobStore

logger = logging.getLogger(__name__)

SCENARIO = "S02-unsupported-patch-fields"
TARGET_FILE = "app/services/device_service.py"
ORIGINAL = (
    "def patch_device(device, fields):\n"
    "    for name, value in fields.items():\n"
    "        setattr(device, name, value)  # BUG: unsupported fields are kept\n"
    "    return device\n"
)
SIMULATION_TICKET = "Simulated run of the S02 ticket: PATCH accepts unsupported fields."
SANDBOX_ROOT = Path(tempfile.gettempdir()) / "jev_agent_simulations"


class SimulatedCrash(BaseException):
    """Stands in for the process being killed mid-step. Not an `Exception`,
    so the runner's step error handling does not catch it and the job is
    left mid-run, exactly as a real crash would leave it."""


class SimulationBusy(RuntimeError):
    """A simulated run is already live; only one runs at a time."""


class NotResumable(RuntimeError):
    """The job is real, finished, or already running."""


@dataclass(frozen=True, slots=True)
class Pacing:
    """Artificial step durations, so a run can be watched step by step.
    The JEV judgment is never delayed: only its real latency shows."""

    propose: float = 1.5
    apply: float = 1.0
    verify: float = 1.5


DEFAULT_PACING = Pacing()
INSTANT = Pacing(propose=0.0, apply=0.0, verify=0.0)


# --- Realistic VERIFY output -------------------------------------------------

# The S02 regression as pytest reports it: a specific, fixable test failure.
FIXABLE_FAILURE = "\n".join(
    [
        "...F" + " " * 69 + "[100%]",
        "=" * 34 + " FAILURES " + "=" * 33,
        "_" * 20 + " test_patch_rejects_unsupported_fields " + "_" * 20,
        "target/fleetops/tests/test_device_service.py:48: in test_patch_rejects_unsupported_fields",
        '    with pytest.raises(ValueError, match="unsupported Device fields"):',
        "E   Failed: DID NOT RAISE ValueError",
        "=" * 27 + " short test summary info " + "=" * 27,
        "FAILED target/fleetops/tests/test_device_service.py"
        "::test_patch_rejects_unsupported_fields",
    ]
)

# The test run cannot even start: the environment is broken, which no new
# code proposal can fix.
ENVIRONMENT_FAILURE = "\n".join(
    [
        "ImportError while loading conftest 'target/fleetops/tests/conftest.py'.",
        "target/fleetops/tests/conftest.py:4: in <module>",
        "    from app.db import engine",
        "target/fleetops/app/db.py:7: in <module>",
        '    engine = create_engine(os.environ["FLEETOPS_DATABASE_URL"])',
        "E   KeyError: 'FLEETOPS_DATABASE_URL'",
        "ERROR: collection of target/fleetops/tests aborted; 0 tests ran",
    ]
)


def _result(pytest_output: str | None) -> VerificationResult:
    """pytest fails with `pytest_output` (or passes when None); Ruff and mypy pass."""
    return VerificationResult(
        checks=[
            CheckResult(
                name="pytest",
                command=["python", "-m", "pytest", "target/fleetops/tests"],
                returncode=0 if pytest_output is None else 1,
                stdout=pytest_output or "",
                stderr="",
            ),
            CheckResult(
                name="ruff",
                command=["python", "-m", "ruff", "check", "target/fleetops"],
                returncode=0,
                stdout="",
                stderr="",
            ),
            CheckResult(
                name="mypy",
                command=["python", "-m", "mypy", "target/fleetops"],
                returncode=0,
                stdout="",
                stderr="",
            ),
        ]
    )


# --- Stories -----------------------------------------------------------------

# What VERIFY does on a given attempt: `None` passes, a string fails with it.
VerifyPlan = Callable[[int], str | None]


def _always(output: str | None) -> VerifyPlan:
    return lambda attempt: output


def _fail_first(output: str) -> VerifyPlan:
    return lambda attempt: output if attempt == 1 else None


@dataclass(frozen=True, slots=True)
class Story:
    name: str
    title: str
    summary: str
    pattern: str
    verify_plan: VerifyPlan
    budget: Budget = DEFAULT_BUDGET
    crash_during_verify: bool = False
    propose_raises: bool = False
    # The verdict the failure text is designed to draw from JEV. The real
    # JEV may disagree; tests and offline runs use it as a stand-in judge.
    intended_verdict: Retryability | None = None


STORIES: tuple[Story, ...] = (
    Story(
        name="happy-path",
        title="Happy path",
        summary="The model proposes a fix, it is applied, and verification passes first time.",
        pattern="Checkpointed steps",
        verify_plan=_always(None),
    ),
    Story(
        name="crash-resume",
        title="Crash and resume",
        summary=(
            "The process dies while verifying. Resume picks up at Verify "
            "without re-proposing or re-applying the fix."
        ),
        pattern="Recovery from checkpoints",
        verify_plan=_always(None),
        crash_during_verify=True,
    ),
    Story(
        name="retry-then-pass",
        title="Retry, then pass",
        summary=(
            "Verification fails with a specific test error. JEV typically judges "
            "it retryable, the change is rolled back, and a fresh attempt passes."
        ),
        pattern="Bounded retry and rollback",
        verify_plan=_fail_first(FIXABLE_FAILURE),
        intended_verdict=Retryability.RETRYABLE,
    ),
    Story(
        name="jev-stop",
        title="JEV says stop",
        summary=(
            "Verification cannot even start: the environment is broken. JEV "
            "typically judges this not retryable, and policy escalates to a person."
        ),
        pattern="JEV judgment under policy authority",
        verify_plan=_always(ENVIRONMENT_FAILURE),
        intended_verdict=Retryability.NOT_RETRYABLE,
    ),
    Story(
        name="retry-budget",
        title="Retry budget runs out",
        summary=(
            "Verification keeps failing. After one retry the budget is spent, "
            "and policy escalates whatever JEV says."
        ),
        pattern="Budgets and escalation",
        verify_plan=_always(FIXABLE_FAILURE),
        budget=Budget(max_retries=1, max_wall_clock_seconds=1800.0),
        intended_verdict=Retryability.RETRYABLE,
    ),
    Story(
        name="wall-clock-budget",
        title="Time budget runs out",
        summary=(
            "The job has only a few seconds of wall-clock budget. When verification "
            "fails after the time is up, policy escalates whatever JEV says."
        ),
        pattern="Budgets and escalation",
        verify_plan=_always(FIXABLE_FAILURE),
        budget=Budget(max_retries=5, max_wall_clock_seconds=3.0),
        intended_verdict=Retryability.RETRYABLE,
    ),
    Story(
        name="step-failure",
        title="A step raises",
        summary="The model call itself fails. A raising step ends the job as Failed, not retried.",
        pattern="Failure handling",
        verify_plan=_always(None),
        propose_raises=True,
    ),
)

STORIES_BY_NAME: dict[str, Story] = {story.name: story for story in STORIES}


def get_story(name: str) -> Story:
    try:
        return STORIES_BY_NAME[name]
    except KeyError:
        raise KeyError(f"Unknown story: {name}") from None


def intended_judge(story: Story) -> JudgeFn:
    """A stand-in judge answering with the story's intended verdict (tests,
    offline seeding). Stories without one raise, like an unavailable JEV."""

    def judge(state: dict[str, object]) -> Judgment:
        if story.intended_verdict is None:
            raise RuntimeError("no intended verdict for this story")
        return Judgment(retryability=story.intended_verdict, confidence=0.9)

    return judge


def jev_configured() -> bool:
    """Whether the real JEV judgment can be called (drives the UI banner)."""
    return bool(os.environ.get("TYPESAFE_API_KEY"))


# --- Running a story ---------------------------------------------------------


def sandbox_dir(job_id: str, root: Path = SANDBOX_ROOT) -> Path:
    """The throwaway 'repo' a simulated job applies its fix to; recreated if
    missing (e.g. the temp dir was cleaned between crash and resume)."""
    sandbox = root / job_id
    target = sandbox / TARGET_FILE
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(ORIGINAL, encoding="utf-8")
    return sandbox


def _current_attempt(store: JobStore, job_id: str) -> int:
    job = store.get_job(job_id)
    if job is None:
        raise KeyError(job_id)
    return job.retry_count + 1


def _verify_entries(store: JobStore, job_id: str, attempt: int) -> int:
    return sum(
        1
        for checkpoint in store.list_checkpoints(job_id)
        if checkpoint.attempt == attempt
        and checkpoint.step is StepName.VERIFY
        and checkpoint.phase is CheckpointPhase.BEFORE
    )


def run_story(
    store: JobStore,
    story: Story,
    job_id: str,
    *,
    pacing: Pacing = DEFAULT_PACING,
    judge_fn: JudgeFn | None = None,
    clock: ClockFn | None = None,
    sandbox_root: Path = SANDBOX_ROOT,
) -> Job:
    """Run, or resume, `job_id` as `story`. Calling it again after a
    `SimulatedCrash` is the resume: checkpoints decide where it continues.

    `judge_fn=None` leaves `run_job` on the real JEV judgment."""
    sandbox = sandbox_dir(job_id, sandbox_root)

    def propose(repo_root: Path, ticket: str) -> FixProposal:
        time.sleep(pacing.propose)
        if story.propose_raises:
            raise RuntimeError("Anthropic API error 529: overloaded (simulated)")
        attempt = _current_attempt(store, job_id)
        return FixProposal(
            file_path=TARGET_FILE,
            explanation=(
                "Reject fields that are not on the Device model with a ValueError "
                f"before applying the patch (attempt {attempt})."
            ),
            new_content=(
                "ALLOWED = {'name', 'status', 'firmware'}\n\n\n"
                "def patch_device(device, fields):\n"
                "    unsupported = set(fields) - ALLOWED\n"
                "    if unsupported:\n"
                "        raise ValueError(f'unsupported Device fields: {unsupported}')\n"
                "    for name, value in fields.items():\n"
                "        setattr(device, name, value)\n"
                "    return device\n"
            ),
        )

    def apply(repo_root: Path, proposal: FixProposal) -> object:
        time.sleep(pacing.apply)
        path = repo_root / proposal.file_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(proposal.new_content, encoding="utf-8")
        return None

    def verify(repo_root: Path) -> VerificationResult:
        time.sleep(pacing.verify)
        attempt = _current_attempt(store, job_id)
        # The runner writes VERIFY's `before` checkpoint before calling us, so
        # one entry means this is the first time VERIFY started this attempt.
        if story.crash_during_verify and _verify_entries(store, job_id, attempt) == 1:
            raise SimulatedCrash
        return _result(story.verify_plan(attempt))

    return run_job(
        store,
        sandbox,
        SIMULATION_TICKET,
        job_id,
        verify_fn=verify,
        judge_fn=judge_fn,
        clock=clock,
        propose_fn=propose,
        apply_fn=apply,
    )


# --- One background run at a time -------------------------------------------

ACTIVE_STATUSES = frozenset(set(JobStatus) - NON_RUNNABLE_JOB_STATUSES)


class SimulationRunner:
    """Starts and resumes simulated jobs on one background thread.

    Owns no job state: the store does. It only knows which job, if any, its
    thread is currently running, so a simulated job that is active in the
    store but not live here was interrupted (the crash story, or the console
    stopped mid-run) and may be resumed."""

    def __init__(
        self,
        store: JobStore,
        *,
        pacing: Pacing = DEFAULT_PACING,
        judge_fn: JudgeFn | None = None,
        clock: ClockFn | None = None,
        sandbox_root: Path = SANDBOX_ROOT,
        background: bool = True,
    ) -> None:
        self._store = store
        self._pacing = pacing
        self._judge_fn = judge_fn
        self._clock = clock
        self._sandbox_root = sandbox_root
        self._background = background
        self._lock = threading.Lock()
        self._live_job_id: str | None = None
        self._thread: threading.Thread | None = None

    @property
    def live_job_id(self) -> str | None:
        return self._live_job_id

    def is_interrupted(self, job: Job) -> bool:
        return (
            job.simulation is not None
            and job.status in ACTIVE_STATUSES
            and job.id != self._live_job_id
        )

    def start(self, story_name: str) -> Job:
        story = get_story(story_name)
        with self._lock:
            self._ensure_idle()
            job = self._store.create_job(SCENARIO, story.budget, simulation=story.name)
            self._launch(story, job.id)
        return job

    def resume(self, job_id: str) -> Job:
        with self._lock:
            job = self._store.get_job(job_id)
            if job is None:
                raise KeyError(job_id)
            if not self.is_interrupted(job):
                raise NotResumable(
                    "Only an interrupted simulated job can be resumed; "
                    f"job {job_id[:8]} is {'real' if job.simulation is None else job.status}."
                )
            self._ensure_idle()
            assert job.simulation is not None
            self._launch(get_story(job.simulation), job.id)
        return job

    def wait(self, timeout: float | None = None) -> None:
        """Block until the live run finishes (tests, shutdown)."""
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def _ensure_idle(self) -> None:
        if self._live_job_id is not None:
            raise SimulationBusy(
                f"A simulated run is already in progress (job {self._live_job_id[:8]}). "
                "Only one runs at a time."
            )

    def _launch(self, story: Story, job_id: str) -> None:
        self._live_job_id = job_id
        if self._background:
            self._thread = threading.Thread(
                target=self._run, args=(story, job_id), name=f"simulation-{job_id[:8]}", daemon=True
            )
            self._thread.start()
        else:
            self._run(story, job_id)

    def _run(self, story: Story, job_id: str) -> None:
        try:
            run_story(
                self._store,
                story,
                job_id,
                pacing=self._pacing,
                judge_fn=self._judge_fn,
                clock=self._clock,
                sandbox_root=self._sandbox_root,
            )
        except SimulatedCrash:
            logger.info("Simulated crash: job %s left interrupted", job_id)
        except Exception:
            logger.exception("Simulated run for job %s stopped unexpectedly", job_id)
        finally:
            self._live_job_id = None
