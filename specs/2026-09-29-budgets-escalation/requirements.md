# Requirements — Milestone 4: Budgets and escalation

Implements `specs/roadmap.md`'s Milestone 4 for Project 2 (`src/jev_agent`).
See `specs/mission.md` and `specs/architecture.md` for program-wide rules;
this file only covers decisions specific to this milestone.

## Scope

- A per-job **budget**: max retries and max wall-clock time, stored on the
  job.
- Policy forces `ESCALATE` when a budget is exceeded, and also when JEV is
  confident a failure is not retryable. `ESCALATE` becomes reachable.
- A durable `escalations` record per escalation, with enough context to
  explain why automation stopped. `WAITING_ON_ESCALATION` becomes a real
  status the runner never resumes.
- **Complete execution history:** every status transition, retry, rollback,
  JEV judgment, step error, and escalation is durably recorded and can
  reconstruct the job's timeline from the store alone.
- Two Milestone 3 carry-overs pulled in (chosen with the user):
  - Fix the crash-after-failed-`VERIFY` resume bug (a job whose checkpointed
    `VERIFY` failed currently resumes as `SUCCEEDED`).
  - Roll back a failed attempt's `APPLY` before the next attempt.

## Decisions

### Which outcomes escalate

`StepOutcome.ESCALATE` is now reachable from a `VERIFY` failure in two ways:

1. **Budget exceeded** — retries used has reached `max_retries`, or elapsed
   wall-clock time has reached `max_wall_clock_seconds`. Forced regardless of
   any JEV judgment.
2. **Confident `NOT_RETRYABLE`** judgment (confidence at or above
   `MIN_JUDGMENT_CONFIDENCE`). `architecture.md` says such failures "warrant
   escalation"; in Milestone 3 this was a stand-in `FAIL`.

`FAILED` is now reserved for **step exceptions** (`PROPOSE`, `APPLY`, or
`VERIFY` raising), as in Milestones 1-3. A missing or low-confidence judgment
still falls back to the fixed retry rule (retry while under budget), unchanged.

Policy order for a `VERIFY` failure:

1. Budget exceeded -> `ESCALATE`.
2. No judgment or confidence below the minimum -> `RETRY`.
3. Confident `NOT_RETRYABLE` -> `ESCALATE`.
4. Confident `RETRYABLE` -> `RETRY`.

Policy stays a pure function of `(retry_count, judgment, budget,
elapsed_seconds)`. JEV still never sets job state.

### Budget shape and configuration

A frozen `Budget` dataclass (`max_retries`, `max_wall_clock_seconds`) stored
as two columns on `jobs`. `create_job` takes an optional `Budget`; the
default is `DEFAULT_MAX_RETRIES = 2` (the Milestone 2 cap, so default behavior
is unchanged) and a generous default wall-clock limit. `MAX_VERIFY_RETRIES`
is replaced by the default. No console-side configuration (Milestone 5).

### Wall-clock measurement

**Elapsed time since the job's `created_at`**, measured with an injectable
clock (`run_job(clock=...)`, defaulting to real UTC now). Downtime between a
crash and a resume counts against the budget, which is the honest wall-clock
meaning. Checked at two decision points only:

- after a `VERIFY` failure, as part of the policy decision above;
- before starting a retry attempt (so a job resumed long after a crash
  escalates instead of spending more).

It is not checked before every step; an attempt already in progress finishes.

### Escalation record

New `escalations` table: id, job id, attempt, reason
(`RETRY_BUDGET_EXHAUSTED`, `WALL_CLOCK_EXCEEDED`, `JEV_NOT_RETRYABLE`),
context JSON, created_at, resolution state (`PENDING` on creation; nothing
resolves it until Milestone 5's console action), nullable resolved_at.
The context holds retry count and max, elapsed and max wall-clock, the
judgment consulted (if any), and the truncated failure output. Escalating
does **not** roll back the applied change: a human should see exactly what
was tried, and the file path and previous content are in the checkpoints.

`WAITING_ON_ESCALATION` joins the runner's non-runnable statuses:
`run_job` returns such a job unchanged, and `find_active_job` does not offer
it for resumption.

### Complete history, written atomically with the change

To stop history from drifting from the state it describes, every status
change goes through one store method that updates the job and appends a
history event **in the same database transaction**. New event types:
`STATUS_TRANSITION` (from, to, reason), `RETRY` (attempt, why), `ROLLBACK`,
`ESCALATION`; existing `JEV_JUDGMENT` and `STEP_ERROR` stay. Creating an
escalation, changing status to `WAITING_ON_ESCALATION`, and appending its
events are likewise one transaction.

### Crash-after-failed-VERIFY

If a job's current attempt has a `VERIFY` `after` checkpoint with
`passed == False` but the decision was never applied (`retry_count` not
advanced, status not final), resume re-enters the **decision path**, not
`SUCCEEDED`. A `JEV_JUDGMENT` event already recorded for that attempt is
reused rather than consulting JEV again, so the decision is stable across
crashes.

### Rollback before retry

When policy decides `RETRY`, the runner first restores the file the failed
attempt's `APPLY` wrote, so the next attempt investigates the original bug
(fixing the demo artifact seen in Milestone 3, where a retry ran against an
already-repaired tree). The previous content is read by the runner and saved
in the attempt's `APPLY` `before` checkpoint **before** `apply_fix` runs;
`ase.apply_fix` is not modified. If `APPLY` is re-entered after a crash, the
saved value is reused, since `apply_fix` would otherwise read the
already-modified file. Rollback writes are idempotent, and a `ROLLBACK`
history event is appended once per attempt (a crash-replay does not duplicate
it).

## Out of scope for this milestone

- Console, and any way to resolve an escalation (Milestone 5).
- More JEV judgment points, or changing `MIN_JUDGMENT_CONFIDENCE` tuning.
- Checking wall-clock before every step; per-step timeouts.
- Rolling back on escalation or on `FAILED`.
- Any change to `src/ase/`, `target/fleetops/`, or `scenarios/S01-*`.
