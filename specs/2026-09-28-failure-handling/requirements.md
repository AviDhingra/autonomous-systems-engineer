# Requirements — Milestone 2: Failure handling

Implements `specs/roadmap.md`'s Milestone 2 for Project 2 (`src/jev_agent`).
See `specs/mission.md` and `specs/architecture.md` for the parts of this that
are already fixed program-wide; this file only covers decisions specific to
this milestone.

## Scope

- Deterministic Python policy that decides `RETRY` or `FAIL` for a failed
  `VERIFY` step. `ESCALATE` is part of the policy's eventual output type
  (per `architecture.md`) but is not reachable yet — budgets and escalation
  are Milestone 4. For this milestone, exhausting retries resolves straight
  to `FAILED`, matching the roadmap's Milestone 2 exit criteria verbatim.
- Retry applies to `VERIFY` failures only. `PROPOSE` and `APPLY` exceptions
  still go straight to `FAILED`, unchanged from Milestone 1. This mirrors
  where the Milestone 3 JEV judgment plugs in (also VERIFY-only), so the
  policy seam built here doesn't need to be reshaped in Milestone 3.
- A fixed retry cap of **2 retries (3 attempts total)**. No per-job budget
  configuration yet (that's Milestone 4) — the cap is a module constant.
- Idempotency under retry, enforced structurally (see Decisions below).

## Decisions

### What a retry actually re-runs

When policy decides `RETRY` after a `VERIFY` failure, the job restarts from
`PROPOSE` — a fresh proposal, fresh apply, fresh verify — not a bare re-run
of `VERIFY` against the same applied file. This matches
`architecture.md`'s note that "a retry of `PROPOSE` starts a fresh proposal
rather than replaying a partial one." It also gives retries a real chance to
fix a genuinely wrong fix, not just a flaky verification run.

Consequence: each retry is a full new **attempt** through
`PROPOSE -> APPLY -> VERIFY`. The checkpoint model must distinguish which
attempt a checkpoint belongs to, or recovery would see attempt 1's `after`
checkpoint for `PROPOSE` and refuse to ever run `PROPOSE` again on retry.
Checkpoints gain an `attempt` number (starting at 1); `Job` gains a
`retry_count` (0 on first attempt, incremented on each `RETRY` decision).
Recovery (`determine_resume_step`) resolves against the checkpoints of the
job's *current* attempt only.

### What "idempotency under retry" means here

Two separate guarantees, not one:

1. **Within an attempt** (already true since Milestone 1, unchanged): a step
   is only ever re-entered if it lacks an `after` checkpoint for that
   attempt. A crash mid-`APPLY` never double-writes the file on resume.
2. **Across attempts** (new in this milestone): a retry never re-applies a
   *stale* proposal. Each attempt's `APPLY` writes the proposal produced by
   *that same attempt's* `PROPOSE`, checkpointed once, never replayed from
   an earlier attempt's state.

Re-applying a file across attempts is expected and intentional (that's the
whole point of restarting from `PROPOSE`) — it is not a violation of
idempotency. What must never happen is applying the same attempt's proposal
twice, or resuming an attempt using another attempt's checkpointed state.

### Deterministic demo/test failures

`PROPOSE` calls the frontier model, so a live run's `VERIFY` outcome isn't
reproducible on demand. To make the retry-exhaustion path (hit the cap,
resolve to `FAILED`) demonstrable and testable on every run, `run_job` gains
an injectable verify callable, defaulting to `ase.verify.verify_repository`.
Tests and the milestone's demo entrypoint can pass a wrapped callable that
forces `VERIFY` to report failure deterministically, independent of what the
LLM actually proposed. This is a Project 2-side seam (dependency injection
at the call site) — it does not modify or wrap anything inside `ase.verify`
itself, consistent with "Project 2 calls Project 1's existing public
functions, it does not modify them."

The scenario used is still `S02-unsupported-patch-fields` (no new scenario
directory needed for this milestone) — the fault-injection wrapper is what
makes the failure path deterministic, not a different scenario.

## Out of scope for this milestone

- JEV / TypeSafe SDK (Milestone 3).
- Budgets, wall-clock limits, `ESCALATE` actually firing, `escalations`
  table, `WAITING_ON_ESCALATION` (Milestone 4).
- `execution_history` table (starts in Milestone 3, completed in Milestone
  4). This milestone's retry activity is visible via `Job.retry_count` and
  the per-attempt checkpoints, not a separate history log.
- Console (Milestone 5).
- Retrying `PROPOSE` or `APPLY` failures directly (only `VERIFY` failures
  trigger the retry policy; see Scope above).
