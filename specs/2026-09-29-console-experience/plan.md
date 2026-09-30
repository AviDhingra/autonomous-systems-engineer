# Plan — Milestone 6: Console experience (post-v1)

Numbered task groups, bottom-up by layer. See `requirements.md` for the
decisions behind these (including the two approved rule changes) and
`specs/architecture.md` / `specs/mission.md` for program-wide rules. Tests
for each group ship with that group. Each group ends with the full
automated gate passing and is committed separately.

## 1. Spec and runner seams

- Update `specs/architecture.md`: console section (may start and resume
  **simulated** runs; never real ones), and `run_job`'s injection seams.
  Add Milestone 6 to `specs/roadmap.md` as post-v1 work.
- `jev_agent/runner.py`: optional `propose_fn` / `apply_fn` parameters on
  `run_job`, defaulting to `propose_fix` / `apply_fix`. No other runner
  change.
- Tests: defaults are the Project 1 functions; injected functions are the
  ones called; existing runner tests pass unchanged.

## 2. Simulated-job marker

- `models.py`: `Job.simulation: str | None = None`.
- `db.py`: nullable `simulation` column on `JobRow`.
- `store.py`: `create_job(..., simulation=None)`; `list_jobs` accepts
  optional filters (status, simulated/real, story, id prefix).
- Tests: round-trip of the marker; each filter; real jobs have `None`.

## 3. Simulation module

- `jev_agent/simulation.py`:
  - `Story` definitions (name, title, one-line explanation, pattern it
    demonstrates, budget) for the seven stories in `requirements.md`.
  - Fake `propose_fn` / `apply_fn` / `verify_fn` per story, with realistic
    failure text per story and injectable pacing (defaults: PROPOSE 1.5s,
    APPLY 1s, VERIFY 1.5s). The judge is the real JEV judgment by default;
    an optional `judge_fn` overrides it (tests only).
  - `jev_configured()` — whether `TYPESAFE_API_KEY` is set (drives the UI
    banner).
  - Per-job sandbox directory under the system temp dir, recreated if
    missing.
  - `run_story(store, story, job_id, pace)` and `resume(store, job_id)`
    calling the real `run_job`; the crash story stops with the job left
    interrupted.
  - `SimulationRunner`: one background thread, one run at a time, knows
    which job (if any) is live; `is_interrupted(job)`.
- Refactor `demo_console_seed.py` onto this module (no more `mock.patch`).
- Tests (zero pacing, fake judge): each story ends in its expected
  status/escalation reason given the judge answer it is designed for; a
  judge that raises follows the fallback path; with no `judge_fn` the real
  `judge_verify_failure` is what `run_job` receives (asserted, not called); crash-resume resumes at VERIFY with one PROPOSE and one APPLY;
  second start while running is refused; `target/fleetops` untouched; the
  existing seed tests still pass.

## 4. Routes and view models

- Routes:
  - `GET /` overview dashboard; `GET /how-it-works`; `GET /tour`;
    `GET /jobs` (filters as query params); existing job, fragment and
    escalation routes kept.
  - `POST /simulations` (story) → starts a run, redirects (303) to the new
    job page; `409` with a readable message if one is already running;
    `422` for an unknown story.
  - `POST /jobs/{id}/resume` → only for interrupted **simulated** jobs;
    `409` for real or non-interrupted jobs.
- View models: dashboard stats and status breakdown; per-attempt stepper
  plus the decision node between attempts (JEV verdict, policy outcome,
  budget then); actor for each step/event; tour steps with their latest
  job.
- `create_app` owns one `SimulationRunner` (injectable pacing for tests).
- Update the read-only test: allowed non-GET routes are exactly resolve,
  start simulation, and resume.
- Tests (`TestClient`): every page 200 with and without data; start →
  303 → job page shows the simulated tag; 409/422 paths; resume only for
  interrupted simulated jobs; filters narrow the jobs list; GET routes
  still never change the store.

## 5. Templates, styling, and interactivity

- New layout: top nav (Overview, How it works, Tour, Jobs, Escalations)
  with a persistent "Run a scenario" button and an escalation count badge;
  a banner when JEV is not configured.
- JEV judgment events show that the answer came from the live JEV API and,
  where JEV disagreed with the story's typical path, the job page still
  explains what policy did with the real answer.
- Overview dashboard: pitch, stat tiles, status breakdown bar, recent jobs,
  run-a-scenario dialog (story cards with explanations).
- How it works: inline SVG governance loop with color-coded actors and a
  legend of who holds authority.
- Job page: pipeline stepper per attempt with step animation while live,
  decision nodes between attempts, Interrupted state with Resume, simulated
  tag, existing escalation cards and timeline (timeline collapsible).
- Tour: step-by-step (Alpine.js), each step with explanation, "Run this
  story", and a link to the latest job.
- Toasts for start/resume/resolve outcomes; loading and empty states;
  responsive down to phone width; visible focus styles.
- htmx and Alpine.js from CDN, pinned; pages render and navigate without
  them.
- Tests: rendered HTML for each page contains its key content; the stepper
  shows the right state per step for each seeded story; polling present
  only for live jobs.

## 6. Verification, evidence, and docs

- Full automated gate (see `validation.md`).
- Manual walkthrough of `validation.md`'s checklist in a real browser,
  including running every story from the UI and the crash-resume flow.
- Screenshots (and a short GIF of a live run) under this spec directory's
  `screenshots/`.
- Update `README.md` (what the console is for, how to launch, how to run a
  story) and mark Milestone 6 complete in `specs/roadmap.md`.
- Update the project memory note.
