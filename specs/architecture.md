# Architecture — JEV-Governed Reliable Engineering Agent (Project 2)

See `mission.md` for why this exists and what "done" means for v1. This file
describes the shape of the system. It describes structure, not
implementation — no Project 2 code exists yet.

## Boundary with Project 1

```text
src/ase/            Project 1 — untouched. propose_fix, apply_fix, verify_repository.
target/fleetops/    The workload Project 1 repairs — untouched.
src/jev_agent/       Project 2 — new. Governs runs of Project 1 as durable jobs.
```

Project 2 calls into Project 1's existing public functions
(`ase.agent.propose_fix`, `ase.apply_fix.apply_fix`,
`ase.verify.verify_repository`) as steps inside a job. It does not modify,
subclass, or reach into their internals. If Project 1's pipeline ever needs
to change to support Project 2, that is a deliberate, explicit decision made
later — not an incidental side effect of building the governance layer.

## Job model

A **job** is one governed run of the Project 1 pipeline against one ticket.
A job progresses through a fixed sequence of **steps**, each individually
checkpointed:

```text
PROPOSE   → ase.agent.propose_fix(...)          produces a FixProposal
APPLY     → ase.apply_fix.apply_fix(...)         writes the proposed file
VERIFY    → ase.verify.verify_repository(...)    runs pytest / Ruff / mypy
```

Each step is checkpointed **before it starts** (so a crash mid-step is
detectable and re-enterable) and **after it completes** (so its result is
durable and the step is never re-executed once it has succeeded). Recovery
means: on restart, read the last checkpoint for a job, and resume at the
first step that has not durably completed — never redo a completed step,
never skip an incomplete one.

Job status is one of: `PENDING`, `RUNNING`, `RETRYING`, `WAITING_ON_ESCALATION`,
`SUCCEEDED`, `FAILED`. Deterministic Python policy code is the only thing
that ever assigns a job's status; JEV and the frontier model never write job
state directly.

## Durable state store

A local SQLite database (via the `sqlalchemy` dependency already in
`pyproject.toml`, separate from `fleetops.db`, e.g. `jev_agent.db`) holds:

- **`jobs`** — id, ticket reference, status, retry count, budget
  configuration, created/updated timestamps.
- **`checkpoints`** — job id, step name, checkpoint phase (`before`/`after`),
  serialized step state, timestamp. This is what recovery reads.
- **`execution_history`** — append-only log of every state transition,
  retry, JEV judgment consulted (with its input/output), and escalation, per
  job. This is what the console displays and what recovery/debugging is
  audited against.
- **`escalations`** — job id, reason, budget/policy context, timestamp,
  resolution state.

SQLite gives real durability (a crash doesn't lose committed state) without
adding new infrastructure, and keeps the single-worker, single-machine scope
honest (see Non-goals in `mission.md`).

## Retry, idempotency, and policy

Retry decisions are made by explicit Python policy functions, not by a
framework's retry decorator and not by JEV. Policy consumes: the step that
failed, how it failed, the job's current retry count and budget, and (at the
one designated decision point — see JEV below) a bounded JEV judgment. Policy
returns one of a small closed set of outcomes: `RETRY`, `ESCALATE`, `FAIL`.

Idempotency is enforced structurally, not by convention:

- `APPLY` is only ever re-entered if its `after` checkpoint is absent —
  once a file write is durably checkpointed as complete, it is not repeated.
- `VERIFY` re-running is safe by construction (it only reads and runs
  checks; it doesn't mutate state), so it's the natural retry target for
  most failures.
- A retry of `PROPOSE` starts a fresh proposal rather than replaying a
  partial one — Project 1's `propose_fix` has no partial-completion state of
  its own to resume.

## JEV judgment seam

Exactly one narrow, bounded judgment is wired in for v1, at the point where
policy decides what to do after a `VERIFY` failure:

> Given the verification failure output, is this failure **retryable**
> (e.g. transient, or plausibly fixed by re-proposing) or does it warrant
> **escalation** (e.g. the same class of failure keeps recurring, or the
> failure indicates a deeper problem than a bounded retry can address)?

JEV returns a typed, bounded judgment (a classification, optionally with a
confidence signal) via the TypeSafe SDK. **JEV never decides the outcome
itself.** Its judgment is one input to the deterministic policy function
described above, alongside the retry count and budget — policy always has
final say, and a JEV call that fails, times out, or returns a low-confidence
result is itself handled by explicit fallback policy (e.g. default to
`ESCALATE` rather than guessing).

## Budgets and escalation

Each job has a budget (initially: max retry count and max wall-clock time,
configurable per job). When a policy decision would exceed the budget, the
outcome is forced to `ESCALATE` regardless of what JEV or retry logic would
otherwise choose. An escalation is a durable record (`escalations` table)
with enough context to explain, after the fact, exactly why the job stopped
making automated progress. Escalation is a terminal-for-now state
(`WAITING_ON_ESCALATION`) — resolving it is a manual action available through
the console, not an automated retry path.

## Execution console

A small local FastAPI web app under `src/jev_agent/console/` (name indicative,
not final) that reads from the same SQLite store and shows:

- the list of jobs and their current status,
- a job's timeline of checkpoints and step results,
- its execution history (including JEV judgments consulted and their
  outputs),
- any pending escalations, with enough detail to understand and resolve them.

The console is read-heavy. Its write actions are resolving/acknowledging an
escalation (v1) and, from Milestone 6, starting and resuming **simulated**
runs: preset stories that drive the real `run_job` with fake PROPOSE,
APPLY, and VERIFY steps (via `run_job`'s `propose_fn` / `apply_fn` /
`verify_fn` seams) and the real JEV judgment. The console never starts,
resumes, or retries a real run and never calls Project 1, so it can incur
TypeSafe (JEV) cost but never Anthropic cost. One simulated run at a time.
It runs locally, with no auth — see Non-goals in `mission.md`. It is
demo-ready in presentation, not in deployment posture.

## Entrypoints

- `python -m ase.main` remains exactly as it is today: the raw, ungoverned
  Project 1 demo path against S01. Untouched by Project 2.
- Project 2 gets its own new entrypoint (e.g. `python -m jev_agent.main` or
  equivalent) that starts/resumes a governed job and, separately, a way to
  launch the console. The two entrypoints are not merged in v1.

## Forbidden dependencies (reiterated from mission.md)

No LangChain, LangGraph, Celery, Kafka, Temporal, Kubernetes, or generic
workflow engine, in Project 2 or in support of it. State machine, retry, and
scheduling logic here are explicit Python, backed by the SQLite store above.

## Testing

Project 2 code lives under `src/jev_agent/`; its tests live under
`tests/jev_agent/`, mirroring the existing `tests/ase/` layout and using the
same pytest/Ruff/mypy gates already configured in `pyproject.toml`. Recovery
behavior (kill-and-resume) should be testable without actually killing a
process — e.g. by constructing a store with a job left mid-checkpoint and
asserting the recovery path resumes at the correct step.
