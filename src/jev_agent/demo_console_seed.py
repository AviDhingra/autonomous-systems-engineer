"""Milestone 5 demo data: populate a database so the console shows every story.

Drives the real `run_job` with injected fakes (no network, no API keys, no
`target/fleetops` changes) against a throwaway temp repo, and writes to the
database you name. The stories, one job each:

  interrupted   killed after APPLY started VERIFY, resumed, succeeded
  retried       VERIFY failed once (JEV unavailable -> fixed rule), then passed
  jev-retry     a confident "retryable" judgment, then a passing retry
  jev-stop      a confident "not retryable" judgment -> escalation
  retry-budget  VERIFY keeps failing -> retry budget exhausted -> escalation
  wall-clock    the time budget runs out -> escalation (takes ~2.5s of real time)
  resolved      an escalation a person has since resolved
  failed        PROPOSE raised -> FAILED

Usage:
    python -m jev_agent.demo_console_seed                       # ./demo_console.db
    python -m jev_agent.demo_console_seed --database-url sqlite:///x.db --reset
    python -m jev_agent.console --database-url sqlite:///./demo_console.db
"""

import argparse
import contextlib
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from ase.models import FixProposal
from ase.verify import CheckResult, VerificationResult
from jev_agent import runner as runner_module
from jev_agent.models import Budget, Job, Judgment, Retryability
from jev_agent.runner import run_job
from jev_agent.store import JobStore

SCENARIO = "S02-unsupported-patch-fields"
DEFAULT_DATABASE_URL = "sqlite:///./demo_console.db"
TARGET_FILE = "app/mod.py"
ORIGINAL = "def patch(fields):\n    return fields  # BUG: unsupported fields are kept\n"
FAIL_PROPOSE_TICKET = "seed:propose-raises"
WALL_CLOCK_SECONDS = 2.0

FAILURE_TEXT = (
    "FAILED tests/test_vehicles.py::test_patch_rejects_unsupported_fields - "
    "AssertionError: assert 200 == 422"
)


class SimulatedCrash(BaseException):
    """Stands in for the process being killed: not an `Exception`, so the
    runner's step error handling does not catch it and the job is left mid-run."""


def _check(passed: bool) -> CheckResult:
    return CheckResult(
        name="pytest",
        command=["pytest"],
        returncode=0 if passed else 1,
        stdout="" if passed else FAILURE_TEXT,
        stderr="",
    )


def _passing(repo_root: Path) -> VerificationResult:
    return VerificationResult(checks=[_check(True)])


def _failing(repo_root: Path) -> VerificationResult:
    return VerificationResult(checks=[_check(False)])


def _fail_then_pass() -> "VerifyFn":
    calls = 0

    def verify(repo_root: Path) -> VerificationResult:
        nonlocal calls
        calls += 1
        return _failing(repo_root) if calls == 1 else _passing(repo_root)

    return verify


def _judge(retryability: Retryability, confidence: float) -> "JudgeFn":
    def judge(state: dict[str, object]) -> Judgment:
        return Judgment(retryability=retryability, confidence=confidence)

    return judge


def _judge_unavailable(state: dict[str, object]) -> Judgment:
    raise RuntimeError("JEV unavailable")


VerifyFn = runner_module.VerifyFn
JudgeFn = runner_module.JudgeFn


@contextmanager
def _fake_pipeline(repo_root: Path) -> Iterator[None]:
    """Stand-ins for the frontier-model propose and the file-writing apply."""
    (repo_root / "app").mkdir(parents=True, exist_ok=True)
    (repo_root / TARGET_FILE).write_text(ORIGINAL, encoding="utf-8")
    proposals = 0

    def propose(root: Path, ticket: str) -> FixProposal:
        nonlocal proposals
        if ticket == FAIL_PROPOSE_TICKET:
            raise RuntimeError("model call failed: upstream 529 overloaded")
        proposals += 1
        return FixProposal(
            file_path=TARGET_FILE,
            explanation="Reject unsupported fields with a 422.",
            new_content=f"def patch(fields):\n    return validate(fields)  # attempt {proposals}\n",
        )

    def apply(root: Path, proposal: FixProposal) -> str:
        path = root / proposal.file_path
        previous = path.read_text(encoding="utf-8")
        path.write_text(proposal.new_content, encoding="utf-8")
        return previous

    with (
        mock.patch.object(runner_module, "propose_fix", propose),
        mock.patch.object(runner_module, "apply_fix", apply),
    ):
        yield


def seed_demo(store: JobStore) -> dict[str, Job]:
    """Create and run one job per story; returns them by story name."""
    jobs: dict[str, Job] = {}
    with tempfile.TemporaryDirectory() as tmp, _fake_pipeline(Path(tmp)):
        repo = Path(tmp)

        def run(
            name: str,
            verify: VerifyFn,
            judge: JudgeFn = _judge_unavailable,
            budget: Budget | None = None,
            ticket: str = "seed",
        ) -> Job:
            job = store.create_job(SCENARIO, budget) if budget else store.create_job(SCENARIO)
            jobs[name] = run_job(store, repo, ticket, job.id, verify_fn=verify, judge_fn=judge)
            return jobs[name]

        # Killed while VERIFY was running, then resumed by a second run_job.
        crashed = store.create_job(SCENARIO)

        def crash(repo_root: Path) -> VerificationResult:
            raise SimulatedCrash

        with contextlib.suppress(SimulatedCrash):
            run_job(store, repo, "seed", crashed.id, verify_fn=crash, judge_fn=_judge_unavailable)
        jobs["interrupted"] = run_job(
            store, repo, "seed", crashed.id, verify_fn=_passing, judge_fn=_judge_unavailable
        )

        run("retried", _fail_then_pass())
        run("jev-retry", _fail_then_pass(), _judge(Retryability.RETRYABLE, 0.9))
        run("jev-stop", _failing, _judge(Retryability.NOT_RETRYABLE, 0.95))
        run(
            "retry-budget",
            _failing,
            _judge(Retryability.RETRYABLE, 0.8),
            Budget(max_retries=1, max_wall_clock_seconds=1800.0),
        )

        def slow_failure(repo_root: Path) -> VerificationResult:
            time.sleep(WALL_CLOCK_SECONDS + 0.5)
            return _failing(repo_root)

        run(
            "wall-clock",
            slow_failure,
            _judge(Retryability.RETRYABLE, 0.8),
            Budget(max_retries=5, max_wall_clock_seconds=WALL_CLOCK_SECONDS),
        )

        resolved = run(
            "resolved",
            _failing,
            _judge(Retryability.NOT_RETRYABLE, 0.9),
        )
        for escalation in store.list_escalations(resolved.id):
            store.resolve_escalation(escalation.id, "Reviewed by hand; fix tracked separately.")

        run("failed", _passing, ticket=FAIL_PROPOSE_TICKET)
    return jobs


def _sqlite_file(database_url: str) -> Path | None:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix) or database_url == prefix + ":memory:":
        return None
    return Path(database_url.removeprefix(prefix))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else "")
    parser.add_argument("--database-url", default=DEFAULT_DATABASE_URL)
    parser.add_argument(
        "--reset",
        action="store_true",
        help="delete an existing sqlite database file first",
    )
    args = parser.parse_args(argv)

    path = _sqlite_file(args.database_url)
    if args.reset:
        if path is None:
            parser.error("--reset only works with a sqlite:///<file> database URL")
        path.unlink(missing_ok=True)

    store = JobStore(args.database_url)
    if store.list_jobs():
        parser.error(
            f"{args.database_url} already has jobs; pass --reset to recreate it "
            "or choose another --database-url"
        )

    print("Seeding demo jobs (the wall-clock story takes a few seconds)...")
    jobs = seed_demo(store)
    for name, job in jobs.items():
        print(f"  {name:13} {job.id[:8]}  {job.status.value}")
    print(f"\nView them: python -m jev_agent.console --database-url {args.database_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
