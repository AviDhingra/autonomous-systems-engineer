from pathlib import Path

from jev_agent.models import STEP_ORDER, CheckpointPhase, JobStatus
from jev_agent.runner import run_job
from jev_agent.store import JobStore

SCENARIO = "S02-unsupported-patch-fields"
TICKET_PATH = Path(f"scenarios/{SCENARIO}/ticket.md")


def main() -> int:
    repo_root = Path.cwd()
    ticket = (repo_root / TICKET_PATH).read_text(encoding="utf-8")

    store = JobStore()
    job = store.find_active_job(SCENARIO)

    if job is None:
        job = store.create_job(SCENARIO)
        print(f"Starting new job {job.id} for scenario {SCENARIO}")
    else:
        checkpoints = store.list_checkpoints(job.id)
        completed_steps = {
            checkpoint.step
            for checkpoint in checkpoints
            if checkpoint.phase is CheckpointPhase.AFTER
        }
        already_done = [step.value for step in STEP_ORDER if step in completed_steps]
        print(f"Resuming job {job.id} for scenario {SCENARIO}")
        print(
            "Already checkpointed (will not re-run): "
            + (", ".join(already_done) if already_done else "(none)")
        )

    job = run_job(store, repo_root, ticket, job.id)

    print(f"\nJob {job.id} finished with status: {job.status.value}")

    return 0 if job.status is JobStatus.SUCCEEDED else 1


if __name__ == "__main__":
    raise SystemExit(main())
