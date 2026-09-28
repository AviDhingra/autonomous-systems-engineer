# AGENTS.md

Guidance for any AI agent (frontier model, JEV, or otherwise) working in this
repository.

## What's in this repo

- `src/ase/` — **Project 1**, complete. A minimal Claude-powered coding agent
  that investigates a FleetOps bug and proposes/applies/verifies one file
  repair. See `README.md` for its architecture. Treat it as the existing
  engineering workload: read it freely, do not redesign or rewrite it.
- `target/fleetops/` — the FleetOps backend that Project 1 repairs. Also
  existing workload, not to be restructured for Project 2's convenience.
- `scenarios/` — fault scenarios Project 1 (and, going forward, Project 2)
  run against. `S01-duplicate-telemetry` is Project 1's baseline; leave it
  as-is.
- `tests/ase/` — Project 1's tests.
- `specs/` — Project 2's specs. Read `specs/mission.md`,
  `specs/architecture.md`, and `specs/roadmap.md` before doing any Project 2
  work. They are the source of truth for what Project 2 is and how it's
  structured.
- `src/jev_agent/` (not yet created) — where Project 2 code will live, per
  `specs/architecture.md`.

## What Project 2 is

**JEV-Governed Reliable Engineering Agent.** Reliability infrastructure
built *around* Project 1: explicit jobs, durable state, checkpoints,
recovery, retries, idempotency, a JEV-based bounded judgment, deterministic
policy, budgets, escalation, execution history, and an execution console.
Full detail lives in `specs/`. As of this file's creation, no Project 2 code
exists yet — only the spec-driven-development setup (this file plus
`specs/`).

## Non-negotiable architectural rules

- Project 1 is the workload, not something to redesign. Project 2 calls into
  its existing public functions; it does not modify them.
- The frontier model performs complex reasoning (as Project 1 already does).
- JEV provides narrow, bounded judgments only, at specific decision points.
  It never runs jobs, never chooses actions directly, never persists state.
- Deterministic Python always retains authority over state transitions and
  permitted actions. Nothing JEV or the frontier model produces is ever
  applied without passing through explicit Python policy first.
- Prefer explicit Python over orchestration frameworks.
- Do not introduce LangChain, LangGraph, Celery, Kafka, Temporal, Kubernetes,
  or any generic workflow engine — anywhere in this repo, not just in
  Project 2. (Note: `langgraph`, `langchain-anthropic`, and
  `langchain-ollama` are currently unused leftover dependencies in
  `pyproject.toml`. Don't build on them; removing them is a separate,
  explicit cleanup task, not something to do incidentally.)
- Keep the Spec-Driven Development setup minimal: `AGENTS.md` and the three
  files in `specs/` are the whole of it. Don't add process scaffolding
  beyond what's asked for.

## Working conventions (carried over from Project 1)

- Python 3.12, managed via `pyproject.toml`. Dev tooling: `pytest`, `ruff`,
  `mypy` (strict).
- Run checks from the repo root:
  ```powershell
  python -m pytest -q
  python -m ruff check src/ase tests/ase target/fleetops
  python -m mypy src/ase target/fleetops
  ```
  (Project 2 will extend these commands to cover `src/jev_agent` /
  `tests/jev_agent` once that code exists — see `specs/architecture.md`.)
- `ANTHROPIC_API_KEY` must be available as an environment variable to run
  the agent.
- Mirror existing test layout: new tests for Project 2 go in
  `tests/jev_agent/`, parallel to `tests/ase/`.

## Before writing Project 2 code

1. Read `specs/mission.md`, `specs/architecture.md`, and `specs/roadmap.md`.
2. Confirm which milestone (per `specs/roadmap.md`) the work belongs to —
   don't build ahead of the current milestone's scope.
3. If a rule in this file or in `specs/` seems to conflict with what's being
   asked, surface that conflict rather than silently resolving it either
   way.
