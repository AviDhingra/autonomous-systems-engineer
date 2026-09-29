# Plan — Milestone 3: JEV judgment

Numbered task groups. See `requirements.md` for the decisions behind these
and `specs/architecture.md` / `specs/mission.md` for program-wide rules
(Project 1 untouched, deterministic policy has final authority, no
orchestration frameworks, etc.).

## 1. Dependency and judgment module

- `pyproject.toml`: add `typesafe-sdk` as a dependency. No other dependency
  changes.
- Read the current TypeSafe Python SDK docs and the installed package's types
  to confirm the `Choice` question shape, response fields (choice,
  confidence), and exception types before writing code.
- New `jev_agent/models.py` additions: `Retryability` enum
  (`RETRYABLE`, `NOT_RETRYABLE`) and a frozen `Judgment` dataclass
  (`retryability`, `confidence`).
- New `jev_agent/judgment.py`:
  - `judge_verify_failure(failure_output: str, attempt: int,
    prior_failures: list[str]) -> Judgment` calling the sync
    `TypeSafeClient` with one `Choice` question (state and criteria per
    `requirements.md`). Truncate `failure_output` to a fixed max length.
  - Raises on SDK failure/malformed response; it does not swallow errors —
    the runner owns fallback.
  - Returns the exact state dict it sent (or exposes a helper to build it) so
    history can record the judgment input.

## 2. Policy: consume the judgment

- `jev_agent/policy.py`:
  - Add `MIN_JUDGMENT_CONFIDENCE: float = 0.5`.
  - Change to `decide_verify_failure_outcome(retry_count: int,
    judgment: Judgment | None) -> StepOutcome`, implementing the ordered
    rules in `requirements.md` (cap first; `None`/low-confidence -> fixed
    rule; confident `NOT_RETRYABLE` -> `FAIL`; confident `RETRYABLE` ->
    `RETRY`). Still pure: no I/O.
- Update `tests/jev_agent/test_policy.py`: table-driven over
  `retry_count` x judgment (`None`, low-confidence each label, confident
  each label), including the confidence boundary and the retry-cap boundary
  (cap always wins over a confident `RETRYABLE`).

## 3. `execution_history` table and store methods

- `jev_agent/models.py`: `HistoryEvent` dataclass (id, job_id, attempt,
  event_type, payload, created_at) and an `EventType` enum with
  `JEV_JUDGMENT` only.
- `jev_agent/db.py`: `ExecutionHistoryRow` (payload stored as JSON text).
- `jev_agent/store.py`: `append_history_event(job_id, attempt, event_type,
  payload) -> HistoryEvent` and `list_history(job_id) -> list[HistoryEvent]`
  (ordered by id). Append-only: no update or delete methods.
- No migration tooling — SQLite file is demo/dev state, safe to recreate.
- Tests in `tests/jev_agent/test_store.py`: append then list round-trips
  payload; ordering; events are scoped per job.

## 4. Runner: consult judgment, record, apply policy

- `jev_agent/runner.py`:
  - `run_job` gains optional `judge_fn` (default
    `judgment.judge_verify_failure`), alongside `verify_fn`.
  - On a `VERIFY` failure (`passed is False` or the call raises), build the
    failure output text and call `judge_fn` inside try/except; any exception
    -> `judgment = None` and the error text is captured for history.
  - Call `policy.decide_verify_failure_outcome(job.retry_count, judgment)`.
  - Append one `JEV_JUDGMENT` history event (input state, output label +
    confidence or error, decided `StepOutcome`) **before** acting on the
    outcome.
  - Act on the outcome exactly as Milestone 2 (`FAIL` -> `FAILED`;
    `RETRY` -> increment `retry_count`, status `RETRYING`, loop to
    `PROPOSE`).
  - Track failure outputs from earlier attempts in-memory for the
    `prior_failures` input; on resume after a crash, rebuild from prior
    `JEV_JUDGMENT` history events rather than requiring extra state.
- Extend `tests/jev_agent/test_job_runner.py` using a fake `judge_fn`:
  - Confident `RETRYABLE` on every failure -> same bounded-retry behavior as
    Milestone 2 (3 attempts, `FAILED`).
  - Confident `NOT_RETRYABLE` on first failure -> `FAILED` after 1 attempt,
    `retry_count == 0`, exactly one history event.
  - `judge_fn` raising -> job still bounded by the fixed rule; history event
    records the error; job never crashes.
  - Low-confidence judgment -> fixed-rule fallback.
  - One history event per `VERIFY` failure, `outcome` matches what the
    runner actually did, and `retry_count`/status are set by policy only
    (fake judge returning `RETRYABLE` at the cap still ends `FAILED`).
  - Existing Milestone 1/2 runner tests still pass, updated for the new
    default (pass a fake `judge_fn` so no test touches the network).

## 5. Demo entrypoint for a live judgment

- Add `jev_agent/demo_judgment.py` (sibling of `demo_retry.py`): runs the
  `S02-unsupported-patch-fields` scenario with the forced-failure
  `verify_fn` but the **real** `judge_fn`.
- Print, per `VERIFY` failure: the attempt number, the JEV label and
  confidence, the outcome policy chose, and the resulting job status — plus
  a final dump of the job's `execution_history` events read back from the
  store, so the judgment record is visible without opening SQLite.
- Fails fast with a clear message if `TYPESAFE_API_KEY` (or
  `ANTHROPIC_API_KEY`) is unset.

## 6. Full verification pass

- `python -m pytest -q`
- `python -m ruff check src/ase tests/ase target/fleetops src/jev_agent tests/jev_agent`
- `python -m mypy src/ase target/fleetops src/jev_agent`
- Run the Milestone 3 demo once live and confirm output matches
  `validation.md`; record the actual run there.
- Confirm `git diff main --stat` touches nothing under `src/ase/`,
  `target/fleetops/`, or `scenarios/S01-*`.
- Update `specs/roadmap.md` to mark Milestone 3 complete.
