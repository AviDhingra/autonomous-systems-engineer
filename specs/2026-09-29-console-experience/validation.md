# Validation — Milestone 6: Console experience (post-v1)

How to know this work is done and mergeable. The bar: a first-time visitor
understands what the application does and sees its reliability patterns
happen live, without a walkthrough from the person who built it.

## Automated checks (must all pass)

```powershell
python -m pytest -q
python -m ruff check src/ase tests/ase target/fleetops src/jev_agent tests/jev_agent
python -m mypy src/ase target/fleetops src/jev_agent
```

Tests use zero pacing, fake steps, a fake judge, and temp SQLite files;
none may need the network, an API key, a running server, or real waiting.

## Behaviors to confirm via tests (per `plan.md` groups 1–5)

1. **Runner seams:** `run_job` with no `propose_fn`/`apply_fn` uses the
   Project 1 functions; injected ones are called instead. Existing runner,
   recovery, budget and escalation tests pass unchanged.
2. **Every story ends as designed:** happy-path and retry-then-pass
   `SUCCEEDED`; jev-stop, retry-budget, wall-clock-budget
   `WAITING_ON_ESCALATION` with reasons `jev_not_retryable`,
   `retry_budget_exhausted`, `wall_clock_exceeded`; step-failure `FAILED`;
   crash-resume left interrupted, then `SUCCEEDED` after resume with exactly
   one PROPOSE and one APPLY `after` checkpoint.
3. **One run at a time:** starting a simulation while one is live returns
   409 and creates no job.
4. **Resume is scoped:** only an interrupted simulated job can be resumed;
   real jobs and finished jobs get 409 and are not touched.
5. **Console writes are exactly three:** the only non-GET routes are
   resolve escalation, start simulation, and resume simulation; every GET
   route leaves the store unchanged.
6. **Real runs are never started by the console:** no route reaches
   `ase.agent.propose_fix`/`ase.apply_fix.apply_fix` (test patches them to
   raise and exercises every route).
7. **Real JEV by default, fallback when unavailable:** a simulated run with
   no `judge_fn` hands `run_job` the real `judge_verify_failure`; with a
   judge that raises, the story follows the fixed-rule fallback and the
   page shows "JEV judgment unavailable"; the banner appears when
   `TYPESAFE_API_KEY` is unset.
8. **Filters and pages:** `/`, `/how-it-works`, `/tour`, `/jobs` (with each
   filter), job pages and `/escalations` return 200 with data and when
   empty; unknown ids 404.
9. **`target/fleetops` untouched** after running every story.

## Project 1 and core policy untouched

```powershell
git diff main --stat -- src/ase target/fleetops src/jev_agent/policy.py src/jev_agent/recovery.py src/jev_agent/judgment.py
```

must print nothing. `git diff main -- src/jev_agent/runner.py` shows only
the `propose_fn` / `apply_fn` seams.

## Manual walkthrough (real browser)

Needs `TYPESAFE_API_KEY` in the environment (each VERIFY failure makes one
real JEV call). `ANTHROPIC_API_KEY` is not needed.

```powershell
python -m jev_agent.console --database-url sqlite:///./demo_console.db
```

- [ ] A JEV judgment on a simulated run comes from the live API (real
      classification and confidence in history), and policy's outcome
      follows from it.
- [ ] If JEV's answer differs from a story's typical path, the job page
      still makes clear what JEV said and what policy decided.
- [ ] With `TYPESAFE_API_KEY` unset, the banner shows and runs fall back to
      the fixed rule.

- [ ] Landing on `/`, the pitch and the "How it works" link explain the
      purpose in one screen; stat tiles and recent jobs are populated after
      running a story.
- [ ] "How it works" diagram shows who proposes, who judges, and who
      decides, readable without zooming.
- [ ] Every story can be started from the UI; the stepper animates
      Propose → Apply → Verify live; the JEV decision appears immediately.
- [ ] retry-then-pass shows the decision node (JEV retryable → policy
      retry), the rollback, and a passing second attempt.
- [ ] crash-resume stops as **Interrupted**; **Resume** continues at
      Verify without re-running Propose or Apply.
- [ ] Budget and jev-stop stories end with an escalation card; resolving it
      shows a toast and the resolved state; the job stays waiting.
- [ ] Starting a second story while one runs shows a clear "one at a time"
      message.
- [ ] The tour walks through all patterns and each "Run this story" works.
- [ ] Jobs filters (status, simulated/real) and id search work.
- [ ] Stopping the console mid-run and restarting shows that job as
      Interrupted with Resume available.
- [ ] Layout works at phone width; controls are keyboard-reachable.
- [ ] With the CDNs blocked, every page still renders and links work.
- [ ] **First-time viewer check:** someone who has not seen the project
      explains its purpose back after five minutes with it.

## Evidence committed

Under `specs/2026-09-29-console-experience/screenshots/`: overview,
how-it-works, a job mid-run, retry-then-pass stepper with decision node,
interrupted crash-resume job, escalation card, tour, and a short GIF of a
story running live.

## Ready to merge when

- All automated checks pass and the tests above exist and pass.
- The diff checks show only the approved runner seams.
- The manual checklist is fully ticked and the evidence is committed.
- `README.md` and `specs/architecture.md` describe the new console
  behavior; `specs/roadmap.md` marks Milestone 6 complete.
- Scope did not grow beyond `requirements.md` (no real-run controls, no
  custom knobs).
