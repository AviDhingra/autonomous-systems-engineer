# Validation — Milestone 1: Durable core

How to know this branch is done and mergeable. Restates
`specs/roadmap.md`'s Milestone 1 exit criteria concretely, against this
branch's actual scenario and file layout.

## Exit criteria (from `specs/roadmap.md`, made concrete)

> A job can be interrupted mid-run (process killed after `APPLY`, before
> `VERIFY` completes) and, on restart, resumes at `VERIFY` without
> re-proposing or re-applying. Demonstrated against the new scenario.

Concretely, for this branch, all of the following must hold:

1. `tests/jev_agent/test_recovery.py` passes: given a store with a job
   whose `PROPOSE` and `APPLY` steps have both `before` and `after`
   checkpoints, and `VERIFY` has only a `before` checkpoint, resuming that
   job calls neither `ase.agent.propose_fix` nor `ase.apply_fix.apply_fix`
   again, proceeds directly to `VERIFY`, and reaches `SUCCEEDED`.
2. `tests/jev_agent/test_job_runner.py` passes: a clean job run against the
   `S02-unsupported-patch-fields` scenario goes `PENDING → RUNNING →
   SUCCEEDED`, with one `before`/`after` checkpoint pair durably recorded
   per step (`PROPOSE`, `APPLY`, `VERIFY`).
3. `python -m jev_agent.main` run manually against `S02`, killed after
   `APPLY`'s `after` checkpoint is written (before `VERIFY` finishes), and
   rerun, visibly resumes at `VERIFY` (per the progress output from
   `plan.md` task 5) rather than re-investigating or re-applying. This is a
   manual sanity pass, not a merge gate — the automated test in (1) is the
   actual proof.

## Scenario correctness (S02)

- Applying `scenarios/S02-unsupported-patch-fields/bug.patch` to a clean
  checkout makes `test_patch_rejects_unsupported_fields` fail and leaves
  every other existing test (`tests/ase/`, the rest of
  `target/fleetops/tests/`) passing — the fault is isolated to the one
  guard clause.
- Reverting `bug.patch` (i.e. the committed baseline) makes
  `test_patch_rejects_unsupported_fields` pass.
- A full job run (task 6's `test_job_runner.py`) against S02 produces a
  file diff equivalent to reverting `bug.patch` — i.e. Project 1's
  `propose_fix`/`apply_fix` independently arrives at (functionally) the
  same guard clause, the way S01's existing demo does.
- `scenarios/S01-duplicate-telemetry/` is byte-for-byte unchanged on this
  branch (`git diff main -- scenarios/S01-duplicate-telemetry` is empty).

## Regression checks (Project 1 untouched)

Run from repo root and confirm all pass, unchanged in behavior from `main`:

```powershell
python -m pytest -q
python -m ruff check src/ase tests/ase target/fleetops
python -m mypy src/ase target/fleetops
```

Additionally:

- `git diff main -- src/ase target/fleetops/app` is empty — Project 1 and
  the FleetOps application code are untouched. (The one intentional
  `target/fleetops` change is the new test in
  `target/fleetops/tests/test_device_service.py` from `plan.md` task 1 —
  `target/fleetops/tests` is expected to differ; `target/fleetops/app` is
  not.)

## New code checks

```powershell
python -m pytest -q tests/jev_agent
python -m ruff check src/jev_agent tests/jev_agent
python -m mypy src/jev_agent
```

All three clean, with `mypy --strict` semantics matching the existing
`pyproject.toml` configuration (no per-module laxer overrides introduced
for `jev_agent`).

## Architectural conformance

- No import of `langgraph`, `langchain_anthropic`, `langchain_ollama`, or
  any other forbidden framework (`AGENTS.md`) anywhere under `src/jev_agent`
  — check with `grep -r` for the package names as a final pass, since
  `ruff`/`mypy` won't catch "used a disallowed but valid import."
- `src/jev_agent` calls only `ase.agent.propose_fix`,
  `ase.apply_fix.apply_fix`, `ase.verify.verify_repository` from Project 1
  — no reach into `ase`'s internals (no importing from `ase.agent`'s
  private helpers, no subclassing Project 1 types).
- Every job status transition traces back to code in `src/jev_agent`, never
  to a value JEV or the frontier model returned directly (moot for this
  milestone since JEV isn't wired in yet, but worth a explicit look at the
  runner code in `plan.md` task 3 to confirm nothing pre-empts Milestone
  3's boundary).
- `jobs`/`checkpoints` tables only — no `execution_history` or
  `escalations` tables created yet (confirm against the store models from
  `plan.md` task 2).

## Explicitly not required to merge this branch

Per `requirements.md`'s "out of scope": no retry logic, no JEV call, no
budget enforcement, no escalation record, no console. A test asserting any
of those exist would be testing the wrong milestone — don't add one.
