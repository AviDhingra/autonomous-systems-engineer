# Requirements — Milestone 6: Console experience (post-v1)

Turns the Milestone 5 execution console into an interactive web application
that a first-time visitor understands without a walkthrough. See
`specs/mission.md` and `specs/architecture.md` for program-wide rules; this
file covers decisions specific to this work, including two deliberate
changes to earlier rules (see "Rule changes").

## Goal

A visitor who has never seen the project should, within a few minutes, be
able to say what it does: **a frontier model proposes code fixes, but
deterministic Python policy decides what happens next — retrying within a
budget, recovering from crashes, consulting a narrow JEV judgment, and
escalating to a human instead of guessing.** They should be able to watch
that happen live, not just read about it.

## Scope

- **Overview dashboard** (`/`): one-line pitch, headline numbers (jobs,
  succeeded, retries, pending escalations), status breakdown, recent jobs,
  and a prominent "Run a scenario" call to action.
- **"How it works" page**: a diagram of the governance loop — Propose
  (frontier model) → Apply → Verify → JEV judgment → deterministic policy →
  retry / escalate / succeed / fail, with budgets and checkpoints — making
  clear which component holds authority at each point.
- **Per-job pipeline stepper**: each attempt drawn as a Propose → Apply →
  Verify track with step states, and a **decision node** between attempts
  showing the JEV verdict, the policy outcome, and the budget at that
  moment. Actors are color-coded (frontier model, Python steps, JEV,
  policy) consistently across the app.
- **Simulated runs from the UI**: pick a story, start it, and watch the job
  move through the stepper live. PROPOSE, APPLY and VERIFY are simulated
  (no Anthropic calls, never touches `target/fleetops`); the **JEV
  judgment is real**, via the TypeSafe API.
- **Guided tour** (`/tour`): one step per reliability pattern
  (checkpointing and recovery, bounded retry and rollback, JEV judgment
  under policy authority, budgets and escalation, human resolution). Each
  step explains the pattern in plain language and offers "Run this story"
  plus a link to the most recent job of that story.
- **Jobs list** moves to `/jobs`, with server-side filters (status,
  simulated/real, story) and search by job id.
- **App-like polish**: consistent navigation, toasts for actions, loading
  and empty states, responsive layout, keyboard-accessible controls.

## Rule changes (explicit, approved by the user)

1. **The console may start work, including real JEV calls.**
   `architecture.md` and the Milestone 5 spec limited the console to reads
   plus resolving escalations. It may now also **start a simulated run**
   and **resume an interrupted simulated run**. A simulated run consults the
   **real JEV judgment via the TypeSafe API**, so the console can now incur
   TypeSafe cost (one call per VERIFY failure). It still never starts,
   resumes, or retries a **real** run and never calls Project 1, so it never
   spends Anthropic credit. `architecture.md`'s console section is updated
   to match.
2. **`run_job` gains two injection seams.** Optional `propose_fn` and
   `apply_fn` parameters on `jev_agent.runner.run_job`, defaulting to
   `ase.agent.propose_fix` and `ase.apply_fix.apply_fix` — the same pattern
   as the existing `verify_fn` / `judge_fn` / `clock`. Behavior with the
   defaults is unchanged. `policy.py`, `recovery.py`, `judgment.py`,
   `src/ase`, and `target/fleetops` stay untouched.

## Decisions

### Simulated runs

- **Stories** (presets only, no custom knobs), each with a one-line
  explanation shown in the UI:
  1. `happy-path` — proposes, applies, verifies first time.
  2. `crash-resume` — the process "dies" during VERIFY; the job is left
     interrupted until the visitor clicks **Resume**, which resumes at
     VERIFY without re-proposing or re-applying.
  3. `retry-then-pass` — VERIFY fails with a specific, fixable test
     failure; JEV is asked; if policy retries, the change is rolled back and
     attempt 2 passes.
  4. `jev-stop` — VERIFY fails with output pointing at a deeper problem
     (e.g. a broken environment) that JEV should judge not retryable; policy
     escalates.
  5. `retry-budget` — VERIFY keeps failing; the retry budget runs out;
     escalation.
  6. `wall-clock-budget` — the time budget runs out; escalation.
  7. `step-failure` — PROPOSE raises; the job ends `FAILED`.
- **Real JEV judgment:** simulated runs call `run_job` without a
  `judge_fn`, so the runner's default — the real
  `judgment.judge_verify_failure` — is used, with its real input and output
  recorded in history. Each story's simulated failure output is realistic
  text chosen to make the intended verdict likely, but **JEV's answer is
  not guaranteed**: if it disagrees, the job follows whatever policy decides
  from the real answer, and the UI shows exactly that. Story descriptions
  say "typically", not "always".
- **JEV unavailable:** if `TYPESAFE_API_KEY` is missing or the call fails,
  the runner's existing fallback applies (fixed retry rule, recorded as
  "JEV judgment unavailable"). Runs still start. The console shows a
  visible banner when the key is not configured so a visitor knows
  judgments will fall back.
- **Pacing:** PROPOSE ~1.5s, APPLY ~1s, VERIFY ~1.5s so the stepper can be
  watched step by step; the JEV judgment gets **no artificial delay** —
  only the API's real latency. Pacing is injectable so tests run at zero
  delay.
- **Tests never call the API:** the simulation module takes an optional
  `judge_fn`; tests always inject a fake.
- **One simulated run at a time** (the single-worker non-goal in
  `mission.md` still holds). Starting a second one while one is running is
  refused with a clear message.
- **Execution:** a single background thread in the console process calls
  the real `run_job` with the story's fake `propose_fn`, `apply_fn`,
  `verify_fn`, and `judge_fn`. All state goes through `JobStore`, so the
  stepper updates via the existing htmx polling.
- **Sandbox files:** each simulated job applies its fake fix to a small
  sandbox directory under the system temp dir, keyed by job id, recreated
  if missing. Never under the repo, never `target/fleetops`.
- **Interrupted jobs:** a simulated job whose status is active but has no
  live thread in this console process (the crash story, or the console was
  stopped mid-run) is shown as **Interrupted** with a **Resume** button.
  Resuming calls `run_job` again — this is the real recovery path, not a
  replay.
- **Shared code:** stories and fakes live in one module
  (`jev_agent/simulation.py`); `demo_console_seed` is refactored to use it
  and drops its `mock.patch` of runner globals. The seed script also uses
  the real JEV judgment by default; tests inject a fake judge.

### Storage

Simulated jobs live in the same store as real ones. `jobs` gains a nullable
`simulation` column holding the story name (`NULL` = real run); `Job` gains
`simulation: str | None = None` and `create_job` an optional `simulation`
argument. The UI tags them "Simulated" and the jobs list can filter them.
No migration tooling — `_check_schema` already rejects an outdated DB file.

### Frontend

Still server-rendered: FastAPI + Jinja2 + htmx, plus **Alpine.js** (CDN,
pinned version) for small client-side behavior (tour stepper, dismissible
toasts, disclosure toggles, the start-run dialog). No build step, no SPA
framework, no Node toolchain. Filters are server-side query parameters so
they are testable. Pages must still render and navigate with the CDNs
unreachable; only live updates and client-side niceties degrade. The
"How it works" diagram is inline SVG, legible at demo-projector size.

## Context

- Milestones 1–5 are complete and merged. The console already has job
  list/detail, history, escalations, resolve, htmx polling of active jobs,
  and a seed script.
- The seed script already drives real `run_job` with fakes; this work turns
  that into a reusable simulation module the console can trigger.

## Out of scope

- Starting, resuming, or retrying **real** (non-simulated) runs from the
  console.
- Custom simulation knobs (failure counts, confidence, budgets, crash point).
- Concurrent runs, auth, multi-user, deployment hardening.
- Any change to `policy.py`, `recovery.py`, `judgment.py`, `src/ase`, or
  `target/fleetops`.
- Removing the unused `langgraph`/`langchain-*` dependencies.
