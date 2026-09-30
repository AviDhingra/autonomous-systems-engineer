"""Demo data: populate a database so the console shows every story at once.

Runs each simulated story from `jev_agent.simulation` (the same ones the
console's "Run a scenario" starts) to completion, plus one escalation that a
person has since resolved. PROPOSE, APPLY and VERIFY are simulated: no
Anthropic calls and no `target/fleetops` changes. The JEV judgment is real
when `TYPESAFE_API_KEY` is set (a handful of TypeSafe calls); without it the
runner's fallback applies and the history says "JEV judgment unavailable".

Usage:
    python -m jev_agent.demo_console_seed                       # ./demo_console.db
    python -m jev_agent.demo_console_seed --database-url sqlite:///x.db --reset
    python -m jev_agent.console --database-url sqlite:///./demo_console.db
"""

import argparse
from datetime import UTC, datetime, timedelta
from pathlib import Path

from jev_agent.models import Job
from jev_agent.simulation import (
    DEFAULT_PACING,
    INSTANT,
    SANDBOX_ROOT,
    SCENARIO,
    STORIES,
    SimulatedCrash,
    Story,
    get_story,
    intended_judge,
    jev_configured,
    run_story,
)
from jev_agent.store import JobStore

DEFAULT_DATABASE_URL = "sqlite:///./demo_console.db"
RESOLVED = "resolved"
RESOLUTION_NOTE = "Reviewed by hand: the test environment was fixed separately."

__all__ = ["DEFAULT_DATABASE_URL", "SCENARIO", "main", "seed_demo"]


def _an_hour_later() -> datetime:
    return datetime.now(UTC) + timedelta(hours=1)


def seed_demo(
    store: JobStore,
    *,
    stand_in_judges: bool = False,
    instant: bool = False,
    sandbox_root: Path = SANDBOX_ROOT,
) -> dict[str, Job]:
    """Run every story to completion; returns the jobs by story name, plus
    `"resolved"`.

    `stand_in_judges` answers each story with its intended verdict instead of
    calling JEV (tests only). Steps run instantly except the wall-clock story,
    which needs a few real seconds to spend its budget; `instant` fakes that
    story's clock instead (tests only)."""
    jobs: dict[str, Job] = {}

    def run(story: Story, key: str) -> Job:
        job = store.create_job(SCENARIO, story.budget, simulation=story.name)
        wall_clock = story.name == "wall-clock-budget"
        pacing = DEFAULT_PACING if wall_clock and not instant else INSTANT
        judge = intended_judge(story) if stand_in_judges else None
        clock = _an_hour_later if wall_clock and instant else None

        def go() -> Job:
            return run_story(
                store,
                story,
                job.id,
                pacing=pacing,
                judge_fn=judge,
                clock=clock,
                sandbox_root=sandbox_root,
            )

        try:
            result = go()
        except SimulatedCrash:
            # The process "died"; running the story again is the resume.
            result = go()
        jobs[key] = result
        return result

    for story in STORIES:
        run(story, story.name)

    resolved = run(get_story("jev-stop"), RESOLVED)
    for escalation in store.list_escalations(resolved.id):
        store.resolve_escalation(escalation.id, RESOLUTION_NOTE)
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

    if not jev_configured():
        print("TYPESAFE_API_KEY is not set: JEV judgments will fall back to the fixed rule.")
    print("Seeding demo jobs (the time-budget story takes a few seconds)...")
    jobs = seed_demo(store)
    for name, job in jobs.items():
        print(f"  {name:18} {job.id[:8]}  {job.status.value}")
    print(f"\nView them: python -m jev_agent.console --database-url {args.database_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
