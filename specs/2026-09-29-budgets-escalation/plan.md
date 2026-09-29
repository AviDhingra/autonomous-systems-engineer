# Plan — Milestone 4: Budgets and escalation

Numbered task groups. See `requirements.md` for the decisions behind these
and `specs/architecture.md` / `specs/mission.md` for program-wide rules
(Project 1 untouched, deterministic policy has final authority, no
orchestration frameworks, etc.). Tests for each group ship with that group.

## 1. Models and schema

- `jev_agent/models.py`:
  - `Budget` frozen dataclass (`max_retries`, `max_wall_clock_seconds`) and
    `DEFAULT_BUDGET`; add `budget: Budget` to `Job`.
  - `EscalationReason` enum (`RETRY_BUDGET_EXHAUSTED`,
    `WALL_CLOCK_EXCEEDED`, `JEV_NOT_RETRYABLE`), `ResolutionState`
    (`PENDING`, `RESOLVED`), and an `Escalation` dataclass.
  - Extend `EventType` with `STATUS_TRANSITION`, `RETRY`, `ROLLBACK`,
    `ESCALATION`.
  - Add `WAITING_ON_ESCALATION` to the non-runnable status set (rename or
    supplement `TERMINAL_JOB_STATUSES` so both names stay accurate).
- `jev_agent/db.py`: `max_retries` and `max_wall_clock_seconds` columns on
  `JobRow`; new `EscalationRow`.
- No migration tooling — SQLite file is demo/dev state, safe to recreate.

## 2. Store: atomic transitions, escalation, history

- `jev_agent/store.py`:
  - `create_job(scenario, budget=DEFAULT_BUDGET)`.
  - `transition(job_id, status, attempt, reason)`: update status and append a
    `STATUS_TRANSITION` event (from, to, reason) in **one transaction**;
    replaces direct `update_job_status` calls in the runner.
  - `increment_retry_count` also appends a `RETRY` event in the same
    transaction.
  - `escalate(job_id, attempt, reason, context) -> Escalation`: one
    transaction inserting the `escalations` row, moving the job to
    `WAITING_ON_ESCALATION`, and appending `STATUS_TRANSITION` and
    `ESCALATION` events.
  - `list_escalations(job_id)`; `find_active_job` skips
    `WAITING_ON_ESCALATION`.
  - `append_history_event` dedupe helper for per-attempt-once events
    (`ROLLBACK`).
- Tests (`test_store.py`): budget round-trips; `transition` writes exactly
  one event and updates status together; a forced failure mid-transaction
  leaves neither; `escalate` writes row + status + events atomically;
  `find_active_job` ignores waiting jobs.

## 3. Policy: budgets and reachable ESCALATE

- `jev_agent/policy.py`:
  - Replace `MAX_VERIFY_RETRIES` with `DEFAULT_MAX_RETRIES` (still 2).
  - `budget_exceeded(retry_count, elapsed_seconds, budget) ->
    EscalationReason | None` (retry budget checked before wall-clock, so the
    reason is deterministic when both are exceeded).
  - `decide_verify_failure_outcome(retry_count, judgment, budget,
    elapsed_seconds)` implementing the ordered rules in `requirements.md`.
    Still pure: no I/O, no clock.
- Update `tests/jev_agent/test_policy.py`: table-driven over retry count,
  elapsed time (below / at / above the limit), and judgment (`None`, low
  confidence, confident each label). Assert the budget always wins over a
  confident `RETRYABLE`, and that both budget reasons are reported correctly.

## 4. Runner: clock, budget checks, escalation

- `jev_agent/runner.py`:
  - `run_job` gains `clock: Callable[[], datetime]` (default real UTC now).
  - Route every status change through `store.transition`, tagging attempt
    and reason.
  - On a `VERIFY` failure: compute elapsed from `job.created_at`, consult
    JEV (unchanged), call the new policy. `RETRY` continues as today (after
    rollback, group 6); `ESCALATE` calls `store.escalate` with the reason
    and context (retry count/max, elapsed/max, judgment, truncated failure
    output) and returns the job in `WAITING_ON_ESCALATION`.
  - Before starting a retry attempt (including on resume), re-check
    `budget_exceeded`; escalate instead of proceeding if it fires.
  - `WAITING_ON_ESCALATION` jobs are returned unchanged, like terminal ones.
  - Step exceptions still set `FAILED` via `_fail_step` (now through
    `transition`), still recording `STEP_ERROR`.
- Extend `tests/jev_agent/test_job_runner.py` (fake clock, fake judge):
  - Retry budget exhausted -> `WAITING_ON_ESCALATION`, one escalation with
    reason `RETRY_BUDGET_EXHAUSTED`, and `retry_count == max_retries`.
  - Wall-clock exceeded after a `VERIFY` failure -> escalation
    `WALL_CLOCK_EXCEEDED` even under the retry budget.
  - Wall-clock exceeded on resume before a retry attempt -> escalates without
    calling `propose_fix`.
  - Confident `NOT_RETRYABLE` -> escalation `JEV_NOT_RETRYABLE`, not `FAILED`.
  - Per-job budgets differ: a `max_retries=0` job escalates on the first
    failure while a default job retries.
  - A waiting job passed to `run_job` again does not re-run any step.
  - Step exceptions still end `FAILED` with `STEP_ERROR` (no regression).
  - Update Milestone 3 tests whose expected `FAILED` became `ESCALATE`.

## 5. Recovery: fix crash-after-failed-VERIFY

- `jev_agent/recovery.py` / `runner.py`: when the current attempt's steps are
  all complete, inspect its `VERIFY` `after` checkpoint. `passed == True` ->
  `SUCCEEDED`; `passed == False` -> re-enter the decision path (reusing an
  already-recorded `JEV_JUDGMENT` event for that attempt instead of calling
  JEV again).
- Tests: build a store with attempt 1's `VERIFY` `after` checkpoint failed
  and no decision recorded; assert `run_job` reaches retry or escalation,
  never `SUCCEEDED`, and that a recorded judgment is not re-requested
  (`judge_fn` asserts it is not called). Include the same case at the retry
  boundary (last retry used).

## 6. Rollback before retry

- `jev_agent/runner.py`:
  - Before calling `apply_fix`, read the target file's current content and
    save it as `previous_content` in the attempt's `APPLY` `before`
    checkpoint; on re-entry reuse the saved value rather than re-reading.
  - On a `RETRY` decision, write `previous_content` back to the file, then
    append one `ROLLBACK` event (deduped per attempt), then increment the
    retry count and transition to `RETRYING`. Escalation and `FAILED` do not
    roll back.
- Tests: rollback restores the original bytes before the next attempt's
  `PROPOSE`; a crash-replay after rollback but before the retry count
  increments neither corrupts the file nor duplicates the event; re-entering
  `APPLY` after a mid-apply crash restores the true original, not the
  partially applied content; no rollback on escalation.

## 7. History completeness and demo

- Test that a full job's history alone reconstructs its timeline: run a job
  through a retry and an escalation and assert the ordered event types
  (transitions, `JEV_JUDGMENT`, `ROLLBACK`, `RETRY`, `ESCALATION`) match what
  the job actually did, and that no status change exists without an event.
- New `jev_agent/demo_escalation.py` (sibling of `demo_judgment.py`): S02 with
  `injected_bug`, forced-failure `verify_fn` with the realistic pytest text,
  real judge, a small budget (an optional `--budget-seconds` argument to
  demonstrate the wall-clock path). Prints each event from history, then the
  escalation record (reason and context), and the final status.
- Update `jev_agent/main.py` to report `WAITING_ON_ESCALATION` with the
  escalation reason instead of only a success/failure message.

## 8. Full verification pass

- `python -m pytest -q`
- `python -m ruff check src/ase tests/ase target/fleetops src/jev_agent tests/jev_agent`
- `python -m mypy src/ase target/fleetops src/jev_agent`
- Run the live demo once and record it in `validation.md`.
- Confirm `git diff main --stat` touches nothing under `src/ase/`,
  `target/fleetops/`, or `scenarios/S01-*`.
- Update `specs/roadmap.md` to mark Milestone 4 complete.
