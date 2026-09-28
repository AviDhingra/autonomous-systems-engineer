# Plan — Milestone 1: Durable core

Numbered task groups. Each group should land in its own commit (or small
set of commits) and leave the tree in a state where `python -m pytest -q`
passes for everything that exists so far. See `requirements.md` for the
decisions behind these tasks and `validation.md` for how each group's
output gets checked before merge.

## 1. Scenario S02 — unsupported device-patch fields

- Add `test_patch_rejects_unsupported_fields` to
  `target/fleetops/tests/test_device_service.py`, asserting
  `DeviceService.patch()` raises `ValueError` for an unsupported field name
  against the *current* (already-guarded) code. Confirm it passes as-is.
- Create `scenarios/S02-unsupported-patch-fields/ticket.md` (operator-facing
  symptom, no mechanism spoilers — mirror `S01`'s tone and length).
- Create `scenarios/S02-unsupported-patch-fields/bug.patch` that reverts the
  `unexpected_fields` guard in `target/fleetops/app/services/devices.py`
  (and nothing else).
- Manually verify the red/green cycle once, by hand, before wiring anything
  else to it: apply `bug.patch`, confirm
  `test_patch_rejects_unsupported_fields` fails and `python -m ase.main`
  (pointed at S02, see task 5) or a direct `propose_fix`/`apply_fix`/
  `verify_repository` call can fix it; revert the patch application
  afterward so the scenario directory holds the patch file, not a patched
  tree.
- `S01-duplicate-telemetry/` is not touched by this task group.

## 2. Durable state store

- New module, e.g. `src/jev_agent/store.py` (or `store/` package if the
  SQLAlchemy models warrant a split — keep it flat unless it doesn't).
- SQLAlchemy models for `jobs` and `checkpoints` only (per
  `requirements.md`'s "Store schema" section — no `execution_history` or
  `escalations` tables yet).
- Engine/session setup pointed at `jev_agent.db`, created independently of
  `target/fleetops`'s `fleetops.db` (no shared engine, no shared models
  module).
- Minimal store-level API: create job, get job, list checkpoints for a job,
  write a checkpoint (`before`/`after`, step name, serialized state),
  update job status. Keep this to what steps 3–4 actually need — no
  speculative methods.

## 3. Job model and step orchestration

- `Job` status enum matching `requirements.md` (`PENDING`, `RUNNING`,
  `SUCCEEDED`, `FAILED`; `RETRYING`/`WAITING_ON_ESCALATION` defined but
  unreachable this milestone).
- A runner that executes the fixed `PROPOSE → APPLY → VERIFY` sequence:
  - checkpoint `before` a step starts,
  - call the corresponding Project 1 function
    (`ase.agent.propose_fix`, `ase.apply_fix.apply_fix`,
    `ase.verify.verify_repository`) unmodified,
  - checkpoint `after` on success, with enough serialized state (e.g. the
    `FixProposal`, the verification result) that a later step or a status
    report doesn't need to re-derive it.
- On unhandled failure of a step: job status → `FAILED`. No retry, no
  escalation (Milestone 2/4).
- On all three steps completing: job status → `SUCCEEDED`.

## 4. Recovery

- Given a job id, a function that inspects its checkpoints and returns
  "resume at step X" per the semantics in `requirements.md`.
- Wire this into the runner from task 3: starting a job that already has
  checkpoints resumes rather than restarting `PROPOSE`.
- This is the core of the milestone's exit criteria — get it right before
  moving on, since task 6's tests are what prove it.

## 5. CLI entrypoint

- `src/jev_agent/main.py`, runnable as `python -m jev_agent.main`.
- Behavior per `requirements.md`'s "CLI entrypoint shape": run S02 as a job,
  or resume the existing non-terminal job for that scenario if one exists.
- Print step-by-step progress in a form comparable to `ase.main`'s existing
  output (investigate → propose → apply → verify), so a person running it
  can see recovery happening (e.g. "resuming at VERIFY, skipping
  PROPOSE/APPLY — already checkpointed").
- Manual smoke check (not automated, not required for merge, just a sanity
  pass while building): run it, `Ctrl-C` or kill it after `APPLY`'s `after`
  checkpoint is written but before `VERIFY` finishes, rerun it, confirm it
  resumes at `VERIFY`.

## 6. Tests

`tests/jev_agent/`, mirroring `tests/ase/`'s layout:

- `test_store.py` — job/checkpoint CRUD against a temp SQLite file or
  in-memory engine.
- `test_recovery.py` — the milestone's key proof: construct a store with a
  job that has `before`+`after` checkpoints for `PROPOSE` and `APPLY` but
  only a `before` checkpoint for `VERIFY` (i.e. left mid-checkpoint, per
  `requirements.md` decision 2), run the resume path, and assert:
  - `propose_fix` and `apply_fix` are not called again (mock/spy them),
  - the job proceeds directly to `VERIFY`,
  - the job reaches `SUCCEEDED` once `VERIFY` completes.
- `test_job_runner.py` — full run against S02 from a clean job (no
  checkpoints), asserting `PENDING → RUNNING → SUCCEEDED` and one
  checkpoint pair per step, using the real Project 1 functions against the
  S02 scenario (this test needs `ANTHROPIC_API_KEY` and will actually call
  Claude, same as Project 1's own tests presumably do — check
  `tests/ase/` for how it currently handles that before duplicating an
  approach).

## 7. Checks and wiring

- Confirm `python -m pytest -q`, `python -m ruff check src/ase tests/ase
  target/fleetops`, and `python -m mypy src/ase target/fleetops` still pass
  unchanged (i.e. this milestone didn't regress Project 1).
- Extend those commands' scope per `AGENTS.md`'s note that Project 2 will
  extend them to cover `src/jev_agent` / `tests/jev_agent` — add the new
  paths to the same `pytest`/`ruff`/`mypy` invocations (whether that's
  done via `pyproject.toml` config or just documenting the extended CLI
  invocations is an implementation call; prefer config if it avoids
  duplicating path lists in multiple places).
- Confirm no forbidden dependency (`langgraph`, `langchain-*`, or any of
  the other named frameworks) is imported anywhere under `src/jev_agent`.
