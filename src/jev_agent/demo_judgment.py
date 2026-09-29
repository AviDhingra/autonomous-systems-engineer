"""Milestone 3 demo: a real JEV judgment consulted on VERIFY failure.

Like `demo_retry`, VERIFY is forced to fail on every attempt via `run_job`'s
`verify_fn` seam so the failure path is reproducible, but with realistic pytest
failure text (a real assertion failure) so JEV has something meaningful to judge.
Unlike `demo_retry`, the judge is the real TypeSafe Jev SDK. After the run, the job's
`execution_history` is read back from the store so the recorded judgments
(input, output, and the outcome policy chose) are visible without opening
SQLite.

Needs `ANTHROPIC_API_KEY` (PROPOSE) and `TYPESAFE_API_KEY` (JEV).
"""

import os
from pathlib import Path

from ase.verify import CheckResult, VerificationResult
from jev_agent.history_format import format_escalation, format_history
from jev_agent.models import JobStatus
from jev_agent.runner import run_job
from jev_agent.scenario import injected_bug
from jev_agent.store import JobStore

SCENARIO = "S02-unsupported-patch-fields"
TICKET_PATH = Path(f"scenarios/{SCENARIO}/ticket.md")
REQUIRED_ENV_VARS = ("ANTHROPIC_API_KEY", "TYPESAFE_API_KEY")


# Real pytest output, captured by running FleetOps's tests with S02's bug.patch
# applied, so JEV judges the kind of text a genuine VERIFY failure produces.
_REALISTIC_PYTEST_FAILURE = "\n".join(
    [
        "...F" + " " * 69 + "[100%]",
        "=" * 34 + " FAILURES " + "=" * 33,
        "_" * 20 + " test_patch_rejects_unsupported_fields " + "_" * 20,
        "target/fleetops/tests/test_device_service.py:48: in "
        "test_patch_rejects_unsupported_fields",
        '    with pytest.raises(ValueError, match="unsupported Device fields"):',
        "         " + "^" * 60,
        "E   Failed: DID NOT RAISE ValueError",
        "=" * 27 + " short test summary info " + "=" * 27,
        "FAILED target/fleetops/tests/test_device_service.py"
        "::test_patch_rejects_unsupported_fields",
    ]
)


def realistic_failing_verify(repo_root: Path) -> VerificationResult:
    """Force VERIFY to fail on every attempt, with realistic failure text."""
    return VerificationResult(
        checks=[
            CheckResult(
                name="pytest",
                command=["python", "-m", "pytest", "target/fleetops/tests"],
                returncode=1,
                stdout=_REALISTIC_PYTEST_FAILURE,
                stderr="",
            )
        ]
    )


def main() -> int:
    missing = [name for name in REQUIRED_ENV_VARS if not os.environ.get(name)]
    if missing:
        print(f"Missing required environment variable(s): {', '.join(missing)}")
        return 2

    repo_root = Path.cwd()
    ticket = (repo_root / TICKET_PATH).read_text(encoding="utf-8")

    store = JobStore()
    job = store.create_job(SCENARIO)
    print(f"Starting job {job.id} for scenario {SCENARIO} (real JEV judgment demo)")

    with injected_bug(repo_root, SCENARIO):
        job = run_job(store, repo_root, ticket, job.id, verify_fn=realistic_failing_verify)

    print("\nExecution history:")
    print(format_history(store.list_history(job.id)))

    print(f"\nJob {job.id} finished with status: {job.status.value}")
    print(f"Retries consumed: {job.retry_count}")
    for escalation in store.list_escalations(job.id):
        print(format_escalation(escalation))

    return 0 if job.status is JobStatus.WAITING_ON_ESCALATION else 1


if __name__ == "__main__":
    raise SystemExit(main())
