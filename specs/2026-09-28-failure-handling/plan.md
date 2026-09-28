# Plan — Milestone 2: Failure handling

Numbered task groups. See `requirements.md` for the decisions behind these
and `specs/architecture.md` / `specs/mission.md` for program-wide rules
(Project 1 untouched, deterministic policy has final authority, no
orchestration frameworks, etc.).

## 1. Schema and model changes for attempt-scoped checkpoints and retries

- `jev_agent/models.py`: add `retry_count: int` to `Job` (default 0). Add
  `attempt: int` to `Checkpoint`.
- `jev_agent/db.py`: add `retry_count` column to `JobRow` (default 0). Add
  `attempt` column to `CheckpointRow`.
- `jev_agent/store.py`:
  - `create_job` initializes `retry_count=0`.
  - `add_checkpoint` takes an `attempt` argument and persists it.
  - `list_checkpoints` returns `attempt` on each `Checkpoint`.
  - Add `increment_retry_count(job_id) -> Job` (bumps `retry_count`, updates
    `updated_at`).
- No migration tooling needed — SQLite file is demo/dev state, safe to
  recreate.

## 2. Recovery: resolve resume step within the current attempt

- `jev_agent/recovery.py`: `determine_resume_step` takes the target
  `attempt` number and only considers checkpoints matching it. Checkpoints
  from earlier attempts are ignored for resume purposes (they remain in the
  store as history, just not consulted for "what's next").
- Update `tests/jev_agent/test_recovery.py` for the new signature: resuming
  mid-attempt-1 behaves as before; a job with a completed attempt 1 and a
  fresh attempt 2 resumes attempt 2 at `PROPOSE`, not "all done."

## 3. Policy module

- New `jev_agent/policy.py`:
  - `MAX_VERIFY_RETRIES: int = 2` module constant.
  - `StepOutcome` enum (or reuse `JobStatus`-adjacent naming) with at least
    `RETRY` and `FAIL` members; structure it so `ESCALATE` can be added in
    Milestone 4 without a breaking rename.
  - `decide_verify_failure_outcome(retry_count: int) -> StepOutcome`: pure
    function, `RETRY` if `retry_count < MAX_VERIFY_RETRIES` else `FAIL`. No
    I/O, no side effects — this is what Milestone 3 extends to take a JEV
    judgment as an additional input.
- New `tests/jev_agent/test_policy.py`: table-driven tests over
  `retry_count` from 0 through past the cap, asserting the boundary is
  exactly at `MAX_VERIFY_RETRIES`.

## 4. Runner: attempt loop and fault-injection seam

- `jev_agent/runner.py`:
  - `run_job` gains an optional `verify_fn` parameter (defaults to
    `ase.verify.verify_repository`) — the dependency-injection seam for
    deterministic testing/demo, per `requirements.md`.
  - Track the current attempt number (derived from `job.retry_count + 1`).
  - On a `VERIFY` failure (either `result.passed is False` or the call
    raises): call `policy.decide_verify_failure_outcome(job.retry_count)`.
    - `FAIL` -> `update_job_status(FAILED)`, stop.
    - `RETRY` -> `store.increment_retry_count(job_id)`, set status
      `RETRYING`, start a new attempt from `PROPOSE` (loop back rather than
      recursing unboundedly).
  - `PROPOSE`/`APPLY` exceptions remain immediate `FAILED`, unchanged from
    Milestone 1 (see `requirements.md` Scope).
  - Every step-entry still checkpoints `before`/`after` exactly as
    Milestone 1, just tagged with the current attempt.
- Extend `tests/jev_agent/test_job_runner.py`:
  - A `verify_fn` that always fails -> job ends `FAILED` with
    `retry_count == MAX_VERIFY_RETRIES`, and exactly `MAX_VERIFY_RETRIES + 1`
    full sets of PROPOSE/APPLY/VERIFY checkpoints exist (one per attempt).
  - A `verify_fn` that fails once then succeeds -> job ends `SUCCEEDED`
    after exactly 2 attempts, `retry_count == 1`.
  - Idempotency assertion: across attempts, each attempt's `APPLY` writes
    only that attempt's own proposal (mock `apply_fix`/`propose_fix` and
    assert call arguments per attempt, not a stale cross-attempt proposal).
  - Recovery-within-retry: interrupt mid-way through attempt 2 (checkpoint
    a `before` with no `after`) and confirm resume re-enters attempt 2 at
    the right step without touching attempt 1's checkpoints or re-running
    attempt 1.

## 5. Demo entrypoint for retry exhaustion

- Extend `jev_agent/main.py` (or add a small sibling script, e.g.
  `jev_agent/demo_retry.py`, if keeping `main.py` focused on the
  Milestone 1 happy path reads better) to run the `S02` scenario with a
  `verify_fn` wrapper that forces failure on every attempt, so the demo
  deterministically shows: 3 attempts, `retry_count` incrementing each
  time, final status `FAILED`.
- Print enough per-attempt detail (attempt number, step, outcome) that the
  bounded-retry behavior is visible in console output without inspecting
  the SQLite file directly.

## 6. Full verification pass

- `python -m pytest -q`
- `python -m ruff check src/ase tests/ase target/fleetops src/jev_agent tests/jev_agent`
- `python -m mypy src/ase target/fleetops src/jev_agent`
- Run the Milestone 2 demo entrypoint manually once and confirm the printed
  output matches `validation.md`.
- Update `specs/roadmap.md` to mark Milestone 2 complete (mirroring how
  Milestone 1 was marked complete at the start of this work).
