"""Milestone 4 demo: a job that would retry forever hits its budget and escalates.

VERIFY is forced to fail on every attempt (with realistic pytest failure text),
the judge is the real TypeSafe Jev SDK, and the job runs with a small budget.
Rollback restores the buggy file before each retry, so every attempt genuinely
investigates the bug. The job ends `waiting_on_escalation`; the demo then reads
the execution history and the escalation record back from the store.

Usage:
    python -m jev_agent.demo_escalation                    # retry-budget path
    python -m jev_agent.demo_escalation --budget-seconds 5  # wall-clock path

Needs `ANTHROPIC_API_KEY` (PROPOSE) and `TYPESAFE_API_KEY` (JEV).
"""

import argparse
import os
from pathlib import Path

from jev_agent.demo_judgment import (
    REQUIRED_ENV_VARS,
    SCENARIO,
    TICKET_PATH,
    realistic_failing_verify,
)
from jev_agent.history_format import format_escalation, format_history
from jev_agent.models import DEFAULT_MAX_WALL_CLOCK_SECONDS, Budget, JobStatus
from jev_agent.runner import run_job
from jev_agent.scenario import injected_bug
from jev_agent.store import JobStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--budget-seconds", type=float, default=DEFAULT_MAX_WALL_CLOCK_SECONDS)
    args = parser.parse_args(argv)

    missing = [name for name in REQUIRED_ENV_VARS if not os.environ.get(name)]
    if missing:
        print(f"Missing required environment variable(s): {', '.join(missing)}")
        return 2

    repo_root = Path.cwd()
    ticket = (repo_root / TICKET_PATH).read_text(encoding="utf-8")
    budget = Budget(max_retries=args.max_retries, max_wall_clock_seconds=args.budget_seconds)

    store = JobStore()
    job = store.create_job(SCENARIO, budget=budget)
    print(
        f"Starting job {job.id} for scenario {SCENARIO} "
        f"(budget: {budget.max_retries} retries, {budget.max_wall_clock_seconds}s)"
    )

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
