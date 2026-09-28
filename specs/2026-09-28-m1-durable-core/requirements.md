# Requirements — Milestone 1: Durable core

Scope for this feature branch is exactly Milestone 1 of `specs/roadmap.md`.
This file records the scope, the decisions made before implementation
started, and the context an implementer needs without re-reading the whole
history of the conversation that produced it.

## Goal

Stand up `src/jev_agent/` as a governing layer around Project 1's existing
`propose_fix` / `apply_fix` / `verify_repository` functions: a durable,
checkpointed, resumable job, proven against a new scenario. Nothing about
Project 1 (`src/ase/`) or the existing FleetOps baseline (`target/fleetops/`
as exercised by `S01-duplicate-telemetry`) changes.

## In scope for this milestone

- `jobs` and `checkpoints` tables in a new SQLite store (`jev_agent.db`,
  separate from `fleetops.db`), per `specs/architecture.md`.
- A `Job` model that runs the fixed `PROPOSE → APPLY → VERIFY` sequence,
  calling Project 1's public functions unmodified.
- Checkpointing before and after each step.
- Recovery: given a job with a completed `APPLY` checkpoint but no `VERIFY`
  checkpoint, resuming picks up at `VERIFY` — `PROPOSE` and `APPLY` are not
  re-run.
- A new scenario (see below), separate from and not modifying `S01`.
- A minimal CLI entrypoint, `python -m jev_agent.main`, that starts a job for
  the new scenario or resumes an in-progress one.

## Explicitly out of scope for this milestone

Carried directly from `specs/roadmap.md` Milestone 1: retries, idempotency
guarantees beyond what recovery already requires (i.e. `APPLY` is not
re-entered once its `after` checkpoint exists — that's it for this
milestone), JEV, budgets, escalation, the console. A job that fails outright
is simply `FAILED`; there is no retry policy yet. `execution_history` and
`escalations` tables are not created in this milestone — they belong to
Milestone 4's schema needs, and `specs/architecture.md`'s full four-table
description is the eventual end state, not this milestone's.

## Decisions made before implementation (via user sign-off)

1. **New scenario fault** — Claude designs a new, distinct fault (not a
   clone of S01's dedup bug), explores `target/fleetops` to find it, and
   documents the specifics below for review before it's built.
2. **Kill/resume demonstration** — automated test only, per
   `specs/architecture.md`'s own suggestion: construct a store with a job
   left mid-checkpoint (completed `APPLY`, no `VERIFY`) and assert recovery
   resumes at `VERIFY`. No real process is killed as part of proving the
   exit criteria; that keeps the milestone's "demonstrated" claim
   deterministic and CI-friendly.
3. **CLI entrypoint** — built now, in this milestone, not deferred. Matches
   `specs/architecture.md`'s statement that Project 2 gets its own
   entrypoint, and gives the exit criteria something a person can actually
   run (start a job, kill it, rerun, watch it resume at `VERIFY`) in
   addition to the automated test.
4. **Branch / specs directory naming** — `2026-09-28-m1-durable-core`, to
   keep the milestone number explicit for cross-referencing against
   `specs/roadmap.md` later.

## New scenario: S02 — unsupported device-patch fields silently ignored

Separate scenario directory: `scenarios/S02-unsupported-patch-fields/`
(mirrors `S01-duplicate-telemetry/`'s `ticket.md` + `bug.patch` shape).
`S01` is not touched.

**Why this fault, and why it's distinct from S01:** S01 is a *duplicate-write*
bug in the telemetry ingestion path. This one is an *input-validation*
bug in the device-patch path — a different service (`DeviceService`, not
`TelemetryService`), a different failure shape (silently accepting bad
input vs. silently double-writing), and a different fix shape (restoring a
guard clause vs. restoring a dedup check). That gives Project 2's milestones
a second, meaningfully different fault to exercise later (e.g. Milestone 3's
retryable-vs-not JEV judgment benefits from scenarios that don't all look
alike).

**The fault:** `DeviceService.patch()` (`target/fleetops/app/services/devices.py`)
currently validates that `changes` contains only `firmware_version` and
`display_name` and raises `ValueError` on anything else — this guards
callers that go through `DeviceService` directly (e.g. an internal batch
firmware-sync script), not just HTTP callers, since the HTTP layer's
Pydantic model already drops unknown JSON fields before the service ever
sees them. The scenario's `bug.patch` removes that guard, so a
directly-invoked `patch(..., changes={"frimware_version": "2.0.0"})`
(typo'd key) silently no-ops instead of raising — the device's firmware
version is left stale with no error surfaced anywhere.

**Scenario construction (baseline vs. bug.patch), matching S01's pattern:**
- The guard clause already exists in `devices.py` today — that's the
  committed, fixed baseline; it is not being newly added for this scenario.
- One new test, `test_patch_rejects_unsupported_fields`, is added to
  `target/fleetops/tests/test_device_service.py` as part of the committed
  baseline (asserts `ValueError` on an unsupported field name). This is the
  same role S01's pre-existing `test_retry_is_idempotent` plays for that
  scenario.
- `scenarios/S02-unsupported-patch-fields/bug.patch` reverts the guard
  clause in `devices.py` (and only that — no test files touched, matching
  S01's patch shape). Applying it makes
  `test_patch_rejects_unsupported_fields` fail; `verify_repository` should
  fail pre-fix and pass post-fix, exactly like S01.
- `scenarios/S02-unsupported-patch-fields/ticket.md` describes the symptom
  operator-facing (a batch firmware-sync script silently no-ops on a typo'd
  field), not the mechanism, matching S01's ticket phrasing.

This addition to `target/fleetops` (one guard clause's test coverage) is the
same category of change S01 already required to exist as a scenario at all —
it is not a restructuring of FleetOps for Project 2's convenience.

## Store schema (this milestone only)

- **`jobs`** — id, ticket/scenario reference, status
  (`PENDING`/`RUNNING`/`SUCCEEDED`/`FAILED` — `RETRYING` and
  `WAITING_ON_ESCALATION` are not reachable yet since retry/escalation don't
  exist this milestone, but the enum can include them now since
  `architecture.md` defines the full set), created/updated timestamps.
  Retry count and budget columns from `architecture.md` are deferred to
  Milestone 2/4 — do not add unused columns now.
- **`checkpoints`** — job id, step name (`PROPOSE`/`APPLY`/`VERIFY`), phase
  (`before`/`after`), serialized step state, timestamp.

## Recovery semantics for this milestone

On start for a given job id: read its checkpoints, find the latest step with
a durable `after` checkpoint, resume at the next step in sequence. A step
with only a `before` checkpoint (interrupted mid-step) is treated as not
completed and is re-entered from scratch. `APPLY` is idempotent under this
rule structurally (its `after` checkpoint existing means the file write
already happened and is never repeated) — full idempotency-under-retry
(Milestone 2's concern) is not required here since there is no retry loop
yet, only the single crash-and-restart path.

## CLI entrypoint shape

`python -m jev_agent.main` — runs the `S02` scenario as a job. If a job for
that scenario already exists and hasn't reached a terminal status
(`SUCCEEDED`/`FAILED`), it resumes that job at the correct step rather than
starting a new one. Exact argument shape (job id selection, `--new` flag,
etc.) is an implementation detail for `plan.md`, not fixed here.

## Open conflicts / things to flag rather than resolve silently

None identified — this milestone's scope in `specs/roadmap.md` and
`specs/architecture.md` agree, and the decisions above fill the gaps that
were left open for the implementer.
