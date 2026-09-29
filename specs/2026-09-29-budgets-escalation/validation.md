# Validation — Milestone 4: Budgets and escalation

How to know this milestone is done and mergeable. Mirrors the roadmap's
Milestone 4 exit criteria: "a job that would otherwise retry forever instead
hits its budget and escalates, with a readable record of why, in the same
store used by Milestone 1."

## Automated checks (must all pass)

```powershell
python -m pytest -q
python -m ruff check src/ase tests/ase target/fleetops src/jev_agent tests/jev_agent
python -m mypy src/ase target/fleetops src/jev_agent
```

Automated tests use a fake clock and a fake judge; none may need the network,
an API key, or real waiting.

## Specific behaviors to confirm (via tests, per `plan.md` groups 2-7)

1. **Retry budget escalates.** A job whose `VERIFY` always fails ends
   `WAITING_ON_ESCALATION` (not `FAILED`) after `max_retries` retries, with one
   escalation, reason `RETRY_BUDGET_EXHAUSTED`. This is the core proof that a
   would-be infinite retry loop is bounded.
2. **Wall-clock budget escalates.** With a fake clock past
   `max_wall_clock_seconds`, a `VERIFY` failure escalates with reason
   `WALL_CLOCK_EXCEEDED` even under the retry budget; on resume, an expired
   budget escalates before any new attempt runs (`propose_fix` not called).
3. **Budget beats JEV.** A confident `RETRYABLE` judgment cannot push a job
   past either budget.
4. **Confident `NOT_RETRYABLE` escalates** with reason `JEV_NOT_RETRYABLE`;
   missing or low-confidence judgments still fall back to retry while under
   budget.
5. **Budgets are per job.** Two jobs with different budgets behave
   differently in the same test.
6. **Escalation record is readable.** The `escalations` row holds reason,
   attempt, retry count/max, elapsed/max, the judgment consulted, and the
   truncated failure output, with `PENDING` resolution state.
7. **Waiting jobs are not resumed.** `run_job` on a `WAITING_ON_ESCALATION`
   job runs no step, and `find_active_job` does not return it.
8. **`FAILED` is only for step exceptions.** `PROPOSE`/`APPLY`/`VERIFY`
   raising still ends `FAILED` with a `STEP_ERROR` event — no regression.
9. **History is atomic and complete.** Status changes and escalations are
   written in the same transaction as their events (a simulated mid-transaction
   failure leaves neither); a job's ordered history alone reconstructs its
   timeline, and no status change exists without an event.
10. **Crash-after-failed-VERIFY no longer succeeds.** A job with a failed
    `VERIFY` checkpoint and no recorded decision resumes into retry or
    escalation, never `SUCCEEDED`, and an already-recorded judgment is not
    requested again.
11. **Rollback before retry.** The next attempt sees the original file, a
    single `ROLLBACK` event exists per attempt (also after a crash-replay), the
    original is restored correctly after a mid-`APPLY` crash, and nothing is
    rolled back on escalation.
12. **Policy is pure and isolated.** `budget_exceeded` and
    `decide_verify_failure_outcome` have direct unit coverage, including the
    boundary at exactly the budget limit.
13. **No regression.** Milestone 1-3 behavior (resume at the correct step,
    attempt-aware recovery, no double-apply, real-judgment consultation) still
    passes, with tests updated only where `FAIL` legitimately became
    `ESCALATE`.

## Manual live demo (required before merge)

Requires `ANTHROPIC_API_KEY` and `TYPESAFE_API_KEY`. Costs real tokens: each
attempt runs a real investigation (bounded by `MAX_TOOL_TURNS`).

1. Run `python -m jev_agent.demo_escalation` (bug injected, forced `VERIFY`
   failure with realistic pytest text, real judge, small budget).
2. Confirm the printed history shows, in order, job status transitions, one or
   more `jev_judgment` events, a `rollback` before each retry, `retry` events,
   and finally an `escalation` event.
3. Confirm the printed escalation record has a reason, the budget and usage
   numbers, and the failure output, and that the final status is
   `waiting_on_escalation`, with `retry_count` equal to the budget's
   `max_retries`.
4. Run once with `--budget-seconds` small enough to trip wall-clock and
   confirm the reason is `WALL_CLOCK_EXCEEDED`.
5. Confirm `target/fleetops` is back at baseline afterward (`git status`).

Because rollback now restores the original file before each retry, later
attempts should investigate the real bug, unlike Milestone 3's demo. A real
`PROPOSE` can still fail on its own (a `STEP_ERROR`, `FAILED`); that is not a
Milestone 4 defect, since the deterministic paths are proven by the tests.
Record the actual run (date, judgments seen, escalation reason, final status)
in this file when done.

**Actual runs (2026-09-29):** S02 with `bug.patch` injected, forced VERIFY
failure with realistic pytest text, real JEV, `--max-retries 1` (default).

1. **Retry budget** (`python -m jev_agent.demo_escalation`, job
   `0d385fdc-7e19-49a9-aaad-5f5c64b867c0`). Attempt 1: JEV `retryable` at 0.99
   -> `RETRY`; the failed change was rolled back and a `retry` event
   recorded; attempt 2 ran a fresh real investigation on the restored bug.
   Attempt 2: JEV `not_retryable` at 0.2 (below the 0.5 minimum, so ignored),
   yet policy decided `ESCALATE` because the retry budget was spent. Final
   status `waiting_on_escalation`, `retry_count == 1 of 1`, escalation
   `retry_budget_exhausted`, `pending`, elapsed 62.7s of 1800s.
2. **Wall-clock budget** (`--budget-seconds 5`, job
   `1135f786-b789-4a81-ad8c-a5b6636edcdd`). Attempt 1's VERIFY failed after
   42.5s against a 5s budget. JEV said `retryable` at 0.99 and policy
   escalated anyway: escalation `wall_clock_exceeded`, `retry_count 0 of 1`,
   so a confident judgment cannot outrun a budget.

Both runs' printed history showed the ordered transitions, judgments, and (in
run 1) rollback and retry events, ending in the `escalation` event; the store
rows (`jobs`, `escalations`) match the printed status and reason, and
`target/fleetops` was back at baseline afterward.

Two fixes surfaced during the demo and are covered by tests: a stale
`jev_agent.db` from earlier milestones now fails with a clear schema message
instead of an SQL error, and `injected_bug` normalizes a CRLF-checked-out
`bug.patch` (Windows `core.autocrlf`) before applying it.

Not shown live: a confident `not_retryable` escalating on its own with the
budget still available (`JEV_NOT_RETRYABLE`); covered by
`test_confident_not_retryable_escalates_and_low_confidence_falls_back`.

## Definition of done

- All automated checks pass.
- Behaviors 1-13 have passing tests in `tests/jev_agent/`.
- The live demo has been run at least once and ended in a recorded
  escalation, and the run is noted above.
- No new dependencies, and no forbidden frameworks.
- No changes to `src/ase/`, `target/fleetops/`, or `scenarios/S01-*`.
- `specs/roadmap.md` Milestone 4 is marked complete.
