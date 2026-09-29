# Validation — Milestone 5: Execution console

How to know this milestone is done and mergeable. Mirrors the roadmap's
Milestone 5 exit criteria: "the full Milestone 1–4 demo (interrupt-and-resume,
bounded retry, JEV-informed decision, budget-triggered escalation) is
observable end-to-end through the console, in a form presentable to someone
other than just the person who built it."

## Automated checks (must all pass)

```powershell
python -m pytest -q
python -m ruff check src/ase tests/ase target/fleetops src/jev_agent tests/jev_agent
python -m mypy src/ase target/fleetops src/jev_agent
```

Automated tests use a temp SQLite file, fake step functions, a fake judge and
a fake clock; none may need the network, an API key, a running server, or
real waiting.

## Route tests (FastAPI `TestClient`, per `plan.md` groups 1–5)

1. **Job list** shows every seeded job with its status and scenario; empty
   store renders an empty state, not an error.
2. **Job detail** shows checkpoints grouped by attempt, the budget summary
   (retries used/max, elapsed/max), and the job's escalations.
3. **History** renders every `EventType` (status transition, retry, rollback,
   step error, JEV judgment, escalation, escalation resolved) without error,
   in chronological order, JEV events showing classification, confidence and
   the policy outcome.
4. **Pending escalations** lists unresolved escalations with reason and
   context; resolved ones are not listed as pending.
5. **Resolve** (`POST /escalations/{id}/resolve`): escalation becomes
   `RESOLVED` with `resolved_at` and the note; exactly one
   `ESCALATION_RESOLVED` history event; the job **remains
   `WAITING_ON_ESCALATION`**; resolving again adds no second event.
6. **Unknown ids** (job or escalation) return 404, never a 500.
7. **Live refresh is scoped:** a `running`/`retrying` job page carries the
   htmx poll attribute; `succeeded`, `failed` and `waiting_on_escalation`
   pages do not.
8. **Read-only apart from resolve:** a test enumerates the app's routes and
   asserts the only non-`GET` route is the resolve `POST`; another asserts
   the job/checkpoint/history row counts are unchanged after hitting every
   `GET` route.
9. **Seed script:** produces one job per story in `requirements.md` with the
   expected statuses and escalation reasons, and leaves the working tree
   untouched.

## Project 1 and runner untouched

```powershell
git diff main --stat -- src/ase target/fleetops src/jev_agent/runner.py src/jev_agent/policy.py src/jev_agent/recovery.py src/jev_agent/judgment.py
```

must print nothing. Store, model, db and history-format changes are limited to
the resolve path and read helpers described in `plan.md` group 1.

## Manual walkthrough of the seeded demo

```powershell
python -m jev_agent.demo_console_seed --database-url sqlite:///demo_console.db
python -m jev_agent.console --database-url sqlite:///demo_console.db
```

Open `http://127.0.0.1:8000` and confirm each item:

- [ ] Job list shows all statuses: `succeeded`, `failed`,
      `waiting_on_escalation` (and no stale `running` jobs).
- [ ] **Interrupt-and-resume job:** history shows the resume at `VERIFY`
      with no second `PROPOSE`/`APPLY` checkpoint pair for that attempt.
- [ ] **Bounded retry job:** history shows the failed `VERIFY`, a retry
      event, and a passing second attempt; rollback shown before retry.
- [ ] **JEV-informed job:** history shows the judgment (classification and
      confidence) and the policy outcome that followed it.
- [ ] **Retry-budget escalation:** job page shows retries used = max, the
      escalation reason, and the failure output that explains it.
- [ ] **Wall-clock escalation:** job page shows elapsed ≥ max and reason
      `wall_clock_exceeded`.
- [ ] `/escalations` lists the pending escalations; resolving one with a
      note moves it out of pending, adds a history entry, and leaves the job
      `waiting_on_escalation`.
- [ ] The page is understandable to someone who did not build it: labels are
      plain-language, no raw JSON dumps as the primary view.
- [ ] Stopping the server and restarting shows the same data (state is in
      the store, not the process).
- [ ] With a job in a running state (seed or a manual `demo_*` run against
      the same DB), the page updates without a manual reload; with the
      network blocked (htmx CDN unreachable) the pages still render.

## Screenshots committed

Saved under `specs/2026-09-29-execution-console/screenshots/` (browser
captures of the seeded demo):

- `jobs.png` — job list with the mix of statuses.
- `job-retry.png` — detail of the bounded-retry job (attempts, budget panel).
- `job-jev.png` — history showing a JEV judgment and the policy outcome.
- `job-escalated.png` — an escalated job with its escalation context.
- `escalations.png` — pending escalations view, plus the resolved state of
  one after resolving it.

## Ready to merge when

- All automated checks pass and the route tests above exist and pass.
- The Project 1/runner diff check prints nothing.
- The manual checklist is fully ticked and the screenshots are committed.
- `README.md` documents seed + launch; `specs/roadmap.md` marks Milestone 5
  **Complete**.
- Milestone 5's scope did not grow (no launch/requeue/config actions were
  added).
