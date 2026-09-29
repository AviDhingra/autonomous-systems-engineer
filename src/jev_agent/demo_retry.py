"""Milestone 2 demo: bounded retry on VERIFY failure, hitting the cap.

`ase.agent.propose_fix` calls the frontier model, so a live run's VERIFY
outcome isn't reproducible on demand. This demo uses `run_job`'s `verify_fn`
injection seam to force VERIFY to fail on every attempt, independent of what
the LLM actually proposed, so the retry-exhaustion path (bounded retries,
then FAILED) is deterministic and demonstrable on every run.
"""

from pathlib import Path

from ase.verify import CheckResult, VerificationResult
from jev_agent.models import STEP_ORDER, CheckpointPhase, JobStatus, Judgment
from jev_agent.runner import run_job
from jev_agent.scenario import injected_bug
from jev_agent.store import JobStore

SCENARIO = "S02-unsupported-patch-fields"
TICKET_PATH = Path(f"scenarios/{SCENARIO}/ticket.md")


def _always_failing_verify(repo_root: Path) -> VerificationResult:
    return VerificationResult(
        checks=[
            CheckResult(
                name="forced-failure",
                command=["<fault-injection>"],
                returncode=1,
                stdout="",
                stderr="Verification forced to fail for the Milestone 2 retry-exhaustion demo.",
            )
        ]
    )


def _no_judgment(state: dict[str, object]) -> Judgment:
    """Keep this demo about the fixed retry cap: JEV is deliberately not
    consulted, so policy falls back to its fixed rule (see `demo_judgment`)."""
    raise RuntimeError("JEV disabled for the fixed-retry demo")


def main() -> int:
    repo_root = Path.cwd()
    ticket = (repo_root / TICKET_PATH).read_text(encoding="utf-8")

    store = JobStore()
    job = store.create_job(SCENARIO)
    print(f"Starting job {job.id} for scenario {SCENARIO} (forced VERIFY failure demo)")

    with injected_bug(repo_root, SCENARIO):
        job = run_job(
            store,
            repo_root,
            ticket,
            job.id,
            verify_fn=_always_failing_verify,
            judge_fn=_no_judgment,
        )

    checkpoints = store.list_checkpoints(job.id)
    for attempt in sorted({checkpoint.attempt for checkpoint in checkpoints}):
        completed = {
            checkpoint.step
            for checkpoint in checkpoints
            if checkpoint.attempt == attempt and checkpoint.phase is CheckpointPhase.AFTER
        }
        step_summary = ", ".join(
            f"{step.value}={'ok' if step in completed else 'incomplete'}" for step in STEP_ORDER
        )
        print(f"Attempt {attempt}: {step_summary}")

    print(f"\nJob {job.id} finished with status: {job.status.value}")
    print(f"Retries consumed: {job.retry_count}")

    return 0 if job.status is JobStatus.FAILED else 1


if __name__ == "__main__":
    raise SystemExit(main())
