# Roadmap — JEV-Governed Reliable Engineering Agent (Project 2)

See `mission.md` for what "done" means and `architecture.md` for the shape
of the system. This roadmap is intentionally coarse — a handful of large
milestones, each bundling related capabilities, updated as work actually
happens rather than planned in fine-grained detail up front.

No Project 2 code exists yet. Milestone 1 starts from zero.

## Milestone 1 — Durable core — **Complete**

Get the skeleton right before layering anything else on top of it, since
every later milestone depends on jobs actually being resumable.

- Job model and SQLite-backed state store (`jobs`, `checkpoints` tables).
- The three-step job (`PROPOSE` → `APPLY` → `VERIFY`) wrapping Project 1's
  existing functions, with before/after checkpointing per step.
- Recovery: on restart, resume an interrupted job at the correct step
  without redoing completed work.
- The **new reliability scenario** (separate from S01) that this milestone's
  demo runs against.

**Exit criteria:** a job can be interrupted mid-run (process killed after
`APPLY`, before `VERIFY` completes) and, on restart, resumes at `VERIFY`
without re-proposing or re-applying. Demonstrated against the new scenario.

**Explicitly not in this milestone:** retries, idempotency beyond what
recovery already requires, JEV, budgets, escalation, console. A job that
simply fails at this stage is just `FAILED` — no retry logic yet.

## Milestone 2 — Failure handling — **Complete**

- Deterministic policy functions that decide `RETRY` / `ESCALATE` / `FAIL`
  outcomes for a failed step.
- Bounded retry loop (max retry count, no JEV or budget input yet — a fixed
  policy is enough to prove the mechanism).
- Idempotency guarantees under retry: a retried `VERIFY` never re-triggers
  `APPLY`, a retried `PROPOSE` never double-writes a file from a stale
  proposal.

**Exit criteria:** a failing `VERIFY` triggers a bounded number of retries
per policy, without ever double-applying a file change, and eventually
resolves to `FAILED` if retries are exhausted (escalation comes in
Milestone 4).

## Milestone 3 — JEV judgment

- Wire the real TypeSafe Jev SDK for the one designated judgment described
  in `architecture.md` (retryable vs. not, on `VERIFY` failure).
- Update the Milestone 2 policy function to consume that judgment as one
  input, with explicit fallback behavior if the JEV call fails or is
  low-confidence.
- Execution history starts recording each JEV judgment consulted (input,
  output, and what policy decided as a result).

**Exit criteria:** the retry/escalate decision on a `VERIFY` failure visibly
consults a real JEV judgment, and the deterministic policy — not JEV —
remains the thing that actually sets the job's next state.

## Milestone 4 — Budgets and escalation

- Per-job budget (max retries, max wall-clock time).
- Policy forces `ESCALATE` when a budget would otherwise be exceeded, adding
  a durable `escalations` record with enough context to explain why.
- `WAITING_ON_ESCALATION` becomes a real terminal-for-now job status.
- Execution history is now complete: every transition, retry, judgment, and
  escalation for a job is durably recorded and reconstructable after the
  fact.

**Exit criteria:** a job that would otherwise retry forever instead hits its
budget and escalates, with a readable record of why, in the same store used
by Milestone 1.

## Milestone 5 — Execution console

- Small local FastAPI app reading the same SQLite store: job list, job
  detail (checkpoints, step results), execution history, pending
  escalations.
- The one write action the console needs for v1: resolving/acknowledging an
  escalation.

**Exit criteria:** the full Milestone 1–4 demo (interrupt-and-resume, bounded
retry, JEV-informed decision, budget-triggered escalation) is observable
end-to-end through the console, in a form presentable to someone other than
just the person who built it.

## After v1

Not planned in detail yet. Candidates noted for later, not committed:
removing the unused `langgraph`/`langchain-*` dependencies from
`pyproject.toml`; whether `ase.main` and the Project 2 entrypoint should ever
converge; concurrent job execution; additional JEV judgment points beyond
the one in Milestone 3.
