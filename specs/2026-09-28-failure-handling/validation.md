# Validation — Milestone 2: Failure handling

How to know this milestone is actually done and mergeable. Mirrors the
roadmap's Milestone 2 exit criteria: "a failing VERIFY triggers a bounded
number of retries per policy, without ever double-applying a file change,
and eventually resolves to FAILED if retries are exhausted."

## Automated checks (must all pass)

```powershell
python -m pytest -q
python -m ruff check src/ase tests/ase target/fleetops src/jev_agent tests/jev_agent
python -m mypy src/ase target/fleetops src/jev_agent
```

## Specific behaviors to confirm (via tests, listed in `plan.md` section 4)

1. **Bounded retry, exhaustion path.** A `VERIFY` that always fails results
   in exactly `MAX_VERIFY_RETRIES` retries (3 attempts total), then job
   status `FAILED`, with `Job.retry_count == MAX_VERIFY_RETRIES`. No
   unbounded loop — this is the core thing this milestone proves.
2. **Bounded retry, recovery path.** A `VERIFY` that fails once then
   succeeds results in `SUCCEEDED` after exactly 2 attempts,
   `retry_count == 1`.
3. **No double-apply within an attempt.** Unchanged from Milestone 1: a
   crash-and-resume mid-`APPLY` never re-enters `APPLY` once its `after`
   checkpoint exists for that attempt.
4. **No stale-proposal apply across attempts.** Each attempt's `APPLY`
   uses only that same attempt's `PROPOSE` output — never an earlier
   attempt's proposal, never a partial one.
5. **Recovery is attempt-aware.** Interrupting mid-retry (e.g. after
   attempt 2's `PROPOSE` completes, before `APPLY` starts) and resuming
   picks up attempt 2 at `APPLY` — it does not re-run attempt 1, and does
   not treat attempt 1's completed steps as satisfying attempt 2.
6. **`PROPOSE`/`APPLY` failures are still immediate `FAILED`.** Out of
   scope for retry per `requirements.md` — confirm this didn't regress
   from Milestone 1's behavior.
7. **Policy is pure and isolated.** `decide_verify_failure_outcome` has
   direct unit test coverage of the `RETRY`/`FAIL` boundary, independent of
   the runner — this is the function Milestone 3 extends with a JEV input,
   so it needs to be crisply testable on its own.

## Manual demo walkthrough

1. Run the Milestone 2 demo entrypoint (`plan.md` section 5) against
   `S02-unsupported-patch-fields` with the forced-failure `verify_fn`.
2. Confirm console output shows at least one full attempt going through
   `PROPOSE -> APPLY -> VERIFY` with a real Claude investigation, the
   forced `VERIFY` failure correctly triggering a `RETRY` decision, and
   `retry_count` incrementing.
3. Inspect the SQLite store (`jev_agent.db`) directly — e.g. via a quick
   `sqlite3` query or a small ad hoc script — and confirm checkpoint rows
   exist per `attempt`, each attempt having its own `before`/`after` pairs.

**Run against real attempt counts:** since `PROPOSE` calls the real
frontier model on every retry (per `requirements.md`'s "restart from
PROPOSE" decision), a live run's `PROPOSE` call can itself fail
independently of the forced `VERIFY` failure (e.g. `ase/agent.py`'s
`MAX_TOKENS = 4096` truncating a large `new_content` response) — that's
Project 1 behavior, out of bounds to change per `AGENTS.md`. A `PROPOSE`
failure is immediate `FAILED` by design (see `requirements.md` Scope), so
it can end the live demo before the retry cap is reached. That is not a
Milestone 2 defect: the deterministic "hits `MAX_VERIFY_RETRIES` and
resolves to `FAILED`" path is proven reproducibly by the mocked automated
tests in `tests/jev_agent/test_job_runner.py`
(`test_verify_that_always_fails_ends_failed_after_bounded_retries`); the
live demo's job is only to prove the real Project 1 + Project 2 wiring
works end to end, including correct handling of a real `PROPOSE` failure
mid-retry.

**Actual run (2026-09-28):** attempt 1 completed a full real investigation,
proposed a fix, applied it, and the forced `verify_fn` failed it; policy
correctly decided `RETRY` (`retry_count` 0 -> 1). Attempt 2's real
`PROPOSE` call raised before producing a proposal, which correctly resolved
to `FAILED` (not retried, per scope) with `retry_count == 1`. Accepted as
sufficient live-integration evidence per the automated coverage above.

## Definition of done

- All automated checks above pass.
- All behaviors 1-7 have passing test coverage in `tests/jev_agent/`.
- The manual demo walkthrough has been run at least once, exercising a real
  attempt end to end and a real `RETRY` decision (see "Actual run" above).
- `specs/roadmap.md` Milestone 2 is marked complete.
- No changes to `src/ase/`, `target/fleetops/`, or `scenarios/S01-*` —
  Milestone 2 only adds/changes files under `src/jev_agent/` and
  `tests/jev_agent/` (plus this spec directory and the roadmap checkbox).
