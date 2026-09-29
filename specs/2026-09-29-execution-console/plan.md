# Plan — Milestone 5: Execution console

Numbered task groups, bottom-up by layer. See `requirements.md` for the
decisions behind these and `specs/architecture.md` / `specs/mission.md` for
program-wide rules (Project 1 untouched, deterministic policy has final
authority, no orchestration frameworks). Tests for each group ship with that
group. Stay inside this milestone's scope.

## 1. Models, schema, and store additions

- `jev_agent/models.py`: add `EventType.ESCALATION_RESOLVED`; add
  `resolution_note: str | None = None` to `Escalation`.
- `jev_agent/db.py`: nullable `resolution_note` column on `EscalationRow`
  (no migration tooling; recreate the dev DB).
- `jev_agent/store.py`:
  - `list_jobs()` — newest first.
  - `list_pending_escalations()` and `get_escalation(escalation_id)`.
  - `resolve_escalation(escalation_id, note="")` — one transaction: set
    `RESOLVED`, `resolved_at`, note, and append an `ESCALATION_RESOLVED`
    history event. Idempotent for an already-resolved escalation (no second
    event); `KeyError` for an unknown id. Does **not** change job status.
- `jev_agent/history_format.py`: `format_event` case for
  `ESCALATION_RESOLVED`.
- Tests (`test_store.py`, `test_history_format.py`): list ordering; pending
  filter excludes resolved; resolve writes row + event atomically; resolving
  twice adds one event; job status unchanged after resolve; unknown id
  raises.

## 2. Console app skeleton

- Add `jinja2` to `pyproject.toml` dependencies.
- `jev_agent/console/app.py`: `create_app(database_url=DEFAULT_DATABASE_URL)`
  factory returning a FastAPI app that owns one `JobStore`; wires the
  templates and static directory.
- `jev_agent/console/view_models.py`: plain functions/dataclasses turning
  `Job` / `Checkpoint` / `HistoryEvent` / `Escalation` into display-ready
  values (status badge class, per-attempt grouping of checkpoints and
  events, budget usage: retries used/max, elapsed/max, humanized durations,
  JEV judgment summary). Pure, typed, unit-testable without HTTP.
- Tests: view-model unit tests (attempt grouping, budget summary, elapsed
  for running vs. finished jobs, badge mapping for every `JobStatus`).

## 3. Routes

- `GET /` — job list.
- `GET /jobs/{job_id}` — job detail (checkpoints by attempt, budget summary,
  escalations, history).
- `GET /jobs/{job_id}/history` — history fragment (also used for htmx
  polling); `GET /jobs/{job_id}/status` — status/header fragment.
- `GET /escalations` — pending escalations across jobs (resolved ones listed
  separately, collapsed).
- `POST /escalations/{escalation_id}/resolve` — form post with optional
  note; calls `resolve_escalation`, redirects (303) back to the job page.
- 404 page for unknown job/escalation ids; resolve of an unknown id is 404.
- Tests (`tests/jev_agent/test_console.py`, FastAPI `TestClient` against a
  temp SQLite store): each GET returns 200 with expected content; unknown ids
  404; resolve flips the escalation, records a history event, leaves job
  status `WAITING_ON_ESCALATION`; repeat resolve is harmless.

## 4. Templates and styling

- `jev_agent/console/templates/`: `base.html`, `jobs.html`, `job.html`,
  `escalations.html`, plus fragment templates for status and history.
- Per-event-type rendering: status transitions, retries, rollbacks, step
  errors, JEV judgments (classification, confidence, resulting policy
  outcome), escalations (reason, context), resolutions.
- htmx (CDN, pinned) polling on the status and history fragments **only
  while the job is `pending`/`running`/`retrying`**; finished or waiting
  jobs stop polling.
- One hand-written `static/console.css`: light layout, status badges, a
  vertical timeline; readable at demo-projector size; no CSS framework.
- Empty states (no jobs, no pending escalations) with a hint pointing to the
  seed script.
- Tests: rendered HTML contains the poll attribute for a running job and not
  for a finished one; each history event type renders without error.

## 5. Launcher and seed script

- `jev_agent/console/__main__.py`: `python -m jev_agent.console
  [--database-url URL] [--port 8000]` running uvicorn on `127.0.0.1` only.
- `jev_agent/demo_console_seed.py`: build the demo database described in
  `requirements.md` (interrupt-and-resume, bounded retry, JEV-informed,
  retry-budget escalation, wall-clock escalation, resolved escalation,
  `FAILED`) by driving real `run_job` with injected fakes on a temp repo
  copy. Takes `--database-url`; refuses to write into a database that
  already has jobs unless `--reset` is passed.
- Tests (`test_console_seed.py`): seeding a temp DB produces one job per
  intended story with the expected statuses/escalations, needs no network or
  keys, and does not modify the working tree.

## 6. Verification, evidence, and docs

- Run the full automated gate (see `validation.md`).
- Run the seed script, launch the console, and walk the manual checklist in
  `validation.md`.
- Capture the screenshots listed in `validation.md` into this spec
  directory's `screenshots/`.
- Update `README.md` (how to seed and launch the console) and mark
  Milestone 5 **Complete** in `specs/roadmap.md` (also fix its "No Project 2
  code exists yet" line if still present).
- Save a project memory note for Milestone 5 decisions.
