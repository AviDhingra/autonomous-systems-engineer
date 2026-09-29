# Requirements — Milestone 5: Execution console

Implements `specs/roadmap.md`'s Milestone 5 for Project 2 (`src/jev_agent`).
See `specs/mission.md` and `specs/architecture.md` for program-wide rules;
this file only covers decisions specific to this milestone.

## Scope

- A small local **FastAPI** app under `src/jev_agent/console/` reading the
  same SQLite store (`jev_agent.db`) the runner writes:
  - **Job list** — every job, status, scenario, retry count, timestamps.
  - **Job detail** — checkpoints/step results per attempt, a budget summary
    (retries used / max, elapsed / max wall-clock), the job's escalations.
  - **Execution history** — the job's full `execution_history` timeline,
    including JEV judgments (input, output, resulting policy outcome).
  - **Pending escalations** — a cross-job view of unresolved escalations with
    the stored context (reason, retry/elapsed figures, judgment, failure
    output).
- The **one write action**: resolving an escalation.
- **Demo-ready presentation:** clear layout, status badges, readable
  timeline; one hand-written stylesheet. Local, no auth.
- **Live refresh** of status and history while a job runs, via htmx polling.
- A **launcher** (`python -m jev_agent.console`) binding to `127.0.0.1` only.
- A **seed script** that populates a demo database so the full Milestone 1–4
  story is visible without any API spend.

## Decisions

### Rendering: server-rendered Jinja2 + htmx

Pages are Jinja2 templates rendered by FastAPI; htmx (loaded from a CDN,
pinned version) polls small HTML fragment routes (e.g. job status +
history) every few seconds so a running job updates without a page reload.
No JS build step, no SPA framework, no custom JavaScript beyond htmx
attributes. Adds `jinja2` to `pyproject.toml` (FastAPI's template
dependency; not a workflow engine, allowed by `AGENTS.md`). If the page is
opened offline the pages must still render fully (just without auto-refresh).

### Resolving an escalation is record-only

Resolving marks the `escalations` row `RESOLVED`, sets `resolved_at`,
stores an optional free-text note, and appends a history event. **The job
stays `WAITING_ON_ESCALATION`.** This matches `architecture.md` ("resolving
it is a manual action ... not an automated retry path") and the roadmap's
"resolving/acknowledging". It does not move job status, requeue, or touch
the runner — so deterministic policy still owns every state transition, and
the console cannot be used to start work.

The store method (`resolve_escalation`) does the update and the history
event in one transaction, is idempotent (resolving an already-resolved
escalation is a no-op that does not add a second event), and raises for an
unknown id. A new `EventType.ESCALATION_RESOLVED` is added; the existing
`format_event` match gains a case for it.

### Console is read-only apart from resolve

Every route except `POST /escalations/{id}/resolve` is a `GET` that only
reads. The console never creates jobs, never calls `run_job`, and never
calls Project 1. Launching governed runs stays with the CLI entrypoints
(`demo_*`, `main`), so the console can never spend API money.

### Reads go through `JobStore`

The console uses `JobStore` methods, not raw SQL against the tables. Needed
additions (read-only unless noted): `list_jobs()` (newest first),
`list_pending_escalations()`, `get_escalation(id)`, and
`resolve_escalation(id, note)` (the one write). `Escalation` gains a
`resolution_note: str | None` field, backed by a new column on
`EscalationRow`. No migration tooling — `_check_schema` already rejects a
stale DB, and the SQLite file is demo/dev state, safe to recreate.

### Database location

The console takes the database URL from a `--database-url` flag / app
factory argument, defaulting to `DEFAULT_DATABASE_URL`, so tests and the
seeded demo use a separate file and never touch a real `jev_agent.db`.

### Seed script for demo data

`jev_agent.demo_console_seed` drives the real `run_job` with injected fakes
(`verify_fn`, `judge_fn`, `clock`, and monkeypatched `propose_fix` /
`apply_fix` on a temp copy of the repo, as the existing tests do) against a
throwaway SQLite file. It produces one job per story so the console shows:

1. **Interrupt-and-resume** — a job crashed after `APPLY`, resumed at
   `VERIFY`, ends `SUCCEEDED`.
2. **Bounded retry** — `VERIFY` fails, then passes on retry.
3. **JEV-informed decision** — a job with recorded `JEV_JUDGMENT` events
   (retryable and confident-not-retryable).
4. **Budget escalation** — a job that hits its retry budget, plus one that
   hits its wall-clock budget; both `WAITING_ON_ESCALATION` with pending
   escalations.
5. **A resolved escalation** and a **`FAILED`** (step-exception) job, so the
   list shows every status.

No network, no API keys, no `target/fleetops` mutation. It reuses existing
public runner/store APIs; the runner is not changed for the seed's benefit.

### Project 1 and runner untouched

No changes to `src/ase`, `target/fleetops`, `runner.py`, `policy.py`,
`recovery.py`, or `judgment.py`. Store/model/db additions are limited to the
resolve path and read helpers above.

## Context

- Milestones 1–4 are complete: jobs, checkpoints, retries, JEV judgment,
  budgets, escalations, and complete `execution_history` already exist in
  the store; this milestone only displays them and resolves escalations.
- `format_event` / `format_history` in `history_format.py` already render
  history one line per event; the console reuses that text as a starting
  point but renders richer HTML per event type.
- `fastapi`, `uvicorn`, and `httpx` are already dependencies; `httpx` backs
  FastAPI's `TestClient`.
- Exit criterion (roadmap): the full Milestone 1–4 demo is observable
  end-to-end through the console, presentable to someone other than the
  builder.

## Out of scope

- Launching, retrying, requeueing, or cancelling jobs from the console.
- Auth, multi-user, HTTPS, deployment hardening.
- Editing budgets, or any write other than resolving an escalation.
- Removing the unused `langgraph`/`langchain-*` dependencies (separate,
  explicit cleanup — see roadmap "After v1").
- Merging `ase.main` and `jev_agent.main` entrypoints.
