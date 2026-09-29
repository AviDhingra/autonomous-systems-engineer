# Requirements — Milestone 3: JEV judgment

Implements `specs/roadmap.md`'s Milestone 3 for Project 2 (`src/jev_agent`).
See `specs/mission.md` and `specs/architecture.md` for program-wide rules;
this file only covers decisions specific to this milestone.

## Scope

- Wire the real TypeSafe Jev SDK (`typesafe-sdk`) for the one designated
  judgment in `architecture.md`: after a `VERIFY` failure, is the failure
  **retryable** or **not retryable** (escalation-worthy)?
- Extend `policy.decide_verify_failure_outcome` to take that judgment as one
  input alongside `retry_count`, with explicit fallback when the judgment is
  unavailable or low-confidence.
- Start the `execution_history` table, recording each JEV judgment consulted
  (input, output, and the outcome policy decided as a result).
- The judgment is consulted on `VERIFY` failures only, unchanged from
  Milestone 2's retry scope. `PROPOSE`/`APPLY` failures remain immediate
  `FAILED`.

## Decisions

### JEV never decides; policy does

The judgment is a typed value (`RETRYABLE` / `NOT_RETRYABLE` plus a
confidence). Policy consumes it as data. Only `policy.py` produces a
`StepOutcome`, and only the runner (via policy) sets job status. JEV holds no
state and calls nothing.

### Policy rules (in order)

1. Retry budget exhausted (`retry_count >= MAX_VERIFY_RETRIES`) -> `FAIL`,
   regardless of judgment. The Milestone 2 cap still bounds everything.
2. Judgment unavailable (SDK error, timeout, malformed response) ->
   **fall back to the Milestone 2 fixed rule**: `RETRY` while under the cap.
3. Judgment confidence below `MIN_JUDGMENT_CONFIDENCE` -> treated the same as
   unavailable (fixed-rule fallback).
4. Confident `NOT_RETRYABLE` -> `FAIL` **early**, without spending remaining
   retries.
5. Confident `RETRYABLE` -> `RETRY`.

Rationale: `architecture.md` says fallback should default to `ESCALATE`, but
escalation does not exist until Milestone 4. Falling back to the known-safe,
bounded Milestone 2 behavior keeps the job bounded and avoids inventing an
outcome. Likewise a confident `NOT_RETRYABLE` resolves to `FAIL` now; the
Milestone 4 change is to map both it and the fallback to `ESCALATE`.
`StepOutcome.ESCALATE` stays defined but unreachable.

`MIN_JUDGMENT_CONFIDENCE` is a module constant in `policy.py` (starting
value 0.5, per TypeSafe's guidance to start conservative and tune on real
data). It is not per-job configuration (that is Milestone 4).

### The judgment question

Implemented in a new `jev_agent/judgment.py`, one `Choice` question via the
sync `TypeSafeClient`:

- **State:** named fields — the verification failure output (pytest / Ruff /
  mypy text, truncated to a fixed max length), the attempt number, and a
  short summary of prior failure outputs for this job if any (so "same class
  of failure keeps recurring" is answerable).
- **Instructions/criteria:** `retryable` (transient, or plausibly fixed by a
  fresh proposal) vs `not_retryable` (same failure recurring, or a deeper
  problem a bounded retry cannot address).
- Confidence is taken from the Choice response's `confidence` field.
- The exact SDK field names/exception types are confirmed against the
  installed `typesafe-sdk` at implementation time; nothing in the design
  depends on undocumented details.

`TYPESAFE_API_KEY` must be set in the environment for live runs. It is never
written to the store, history, or logs.

### Injectable judge, like `verify_fn`

`run_job` gains an optional `judge_fn` parameter defaulting to the real
`judgment.judge_verify_failure`. Tests pass a fake. Any exception from
`judge_fn` is caught in the runner and treated as "unavailable" (rule 2) —
a JEV failure must never crash or fail a job.

### Minimal `execution_history`

A new `execution_history` table (SQLAlchemy model in `db.py`, methods in
`store.py`), append-only, created now so Milestone 4 extends rather than
migrates it. Columns: id, job id, attempt, event type, JSON payload,
timestamp. Milestone 3 writes two event types. `STEP_ERROR` (added after the first live
demo, where a swallowed `PROPOSE` exception made a failed job undiagnosable)
records step, error type, message, and truncated traceback whenever
`PROPOSE`/`APPLY`/`VERIFY` raises, before the job is marked `FAILED`.
`JEV_JUDGMENT`'s
payload holds the judgment input (the state sent), its output (label,
confidence, or the error if unavailable), and the `StepOutcome` policy
decided. Transitions, retries, and escalations are **not** logged yet
(Milestone 4). The event is written before the runner acts on the outcome.

## Out of scope for this milestone

- Budgets, wall-clock limits, `ESCALATE` firing, `escalations` table,
  `WAITING_ON_ESCALATION` (Milestone 4).
- Logging transitions/retries in `execution_history` (Milestone 4).
- Additional JEV judgment points, or JEV on `PROPOSE`/`APPLY` failures.
- Console (Milestone 5).
- Any change to `src/ase/`, `target/fleetops/`, or `scenarios/S01-*`, except the
  approved exception below.
- Removing unused `langgraph`/`langchain-*` dependencies (separate cleanup).
  Adding `typesafe-sdk` to `pyproject.toml` is the only dependency change.

## Approved exceptions to "Project 1 is untouched"

`ase/agent.py`'s `MAX_TOKENS` was raised from 4096 to 16000 with the
user's explicit approval. The first live demos repeatedly failed `PROPOSE`
with `stop_reason == "max_tokens"` (surfaced by `STEP_ERROR` history events),
even though the fix file is ~500 tokens. 

A second approved edit added `MAX_TOOL_TURNS = 30` to `propose_fix`, which
raises `RuntimeError` when exceeded. The live demo ran an unbounded
investigation (over 100 tool calls, several euros) because the committed
FleetOps baseline is already the *fixed* code and the demos never applied the
scenario's `bug.patch`, so there was nothing to find. The turn cap is a cost
guard; the root-cause fix is `jev_agent/scenario.py`'s `injected_bug`, which
both demos now use to apply `bug.patch` before the run and restore
`target/fleetops` to baseline afterward (refusing to start if that tree is
dirty).
