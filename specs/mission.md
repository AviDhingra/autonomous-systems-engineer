# Mission — JEV-Governed Reliable Engineering Agent (Project 2)

## What this is

Project 1 (`src/ase`) is a minimal, one-shot coding agent: given a ticket, it
investigates FleetOps (`target/fleetops`) with bounded read/search tools,
proposes one file replacement, applies it, and verifies it with pytest, Ruff,
and mypy. It works, but it has no memory between runs, no recovery from a
crash mid-run, no retry policy, and no concept of a budget or escalation. If
the process dies after `apply_fix` but before `verify_repository` finishes,
the run is just gone.

Project 2 does not change any of that. It builds a **reliability layer
around** Project 1: a governing system that runs the Project 1 pipeline as a
durable, resumable, policy-bounded **job**, with a narrow AI judgment (JEV)
consulted at specific decision points and a deterministic Python policy that
always has final authority over what happens next.

Project 1 stays exactly as it is: the workload being governed, not the thing
being redesigned.

## Why

A coding agent that can propose and apply file changes is only as trustworthy
as the infrastructure that runs it. The interesting engineering problem in
Project 2 isn't "can an LLM write a better patch" — it's the boring,
load-bearing stuff that makes an agent safe to run unattended: can a job
survive a crash and resume without redoing completed work, does a failure
retry a bounded number of times instead of looping forever, is the same fix
never double-applied, and when things go wrong (budget exhausted, verification
keeps failing, JEV isn't confident), does the system escalate to a human
instead of guessing.

## Rigor level for v1

This is a **learning-focused demonstration**, not a production system. The
goal is to make the reliability patterns (checkpointing, recovery, retries,
idempotency, bounded judgment, policy, budgets, escalation, history) visibly
and correctly work end to end, using the simplest implementation that
honestly demonstrates each one. It does not need to hold up under concurrent
writers, distributed workers, or adversarial input — those are explicitly
out of scope (see Non-goals).

## What "done" looks like for v1

A **new scenario**, separate from S01, built specifically to exercise the
reliability layer (S01 stays as-is, untouched, as the Project 1 baseline).
The demo must show, against that scenario:

1. A job runs the Project 1 pipeline (propose → apply → verify) as a
   sequence of checkpointed steps.
2. The job process is killed or interrupted mid-run (e.g. after `apply_fix`,
   before verification completes) and, on restart, **resumes from the last
   checkpoint** rather than re-proposing a fix or re-applying an already
   applied change.
3. A failure at some step triggers a **bounded retry** governed by
   deterministic policy, without double-applying or double-verifying
   (idempotency).
4. At least one point in that policy consults a **real JEV judgment** (not a
   stub) — a narrow, bounded classification (e.g. "is this failure
   retryable?") — and the deterministic Python policy, not JEV, decides the
   actual next action based on that judgment.
5. A budget (e.g. max retries, max wall-clock time) is enforced, and
   exceeding it produces an **escalation** rather than an infinite loop or a
   silent failure.
6. Every state transition, retry, judgment, and escalation is recorded in a
   durable **execution history** that can be inspected after the fact.
7. A small **execution console** (demo-ready, not just a local debugging
   tool) lets you see job status, checkpoints, and history for a run.

## JEV scope for v1

JEV is wired in for real in v1 — not deferred to a later milestone. It is
used for exactly one narrow, bounded judgment in the retry/escalation policy
(see `architecture.md` for where). JEV produces a typed judgment; it never
directly executes an action or holds authority over state transitions — that
authority stays with deterministic Python (see Architectural rules below).

## Console audience

The console should be **demo-ready**: presentable to someone other than just
you (a reviewer, a teammate, a portfolio audience), not only a debugging
scratchpad. It still runs locally with no auth and no multi-user concerns —
"demo-ready" is about clarity and polish of what it shows, not about
deployment hardening.

## Architectural rules (non-negotiable, carried from the parent instructions)

- Project 1 (`src/ase`, `target/fleetops`) is the existing engineering
  workload. It is not redesigned or rewritten by Project 2.
- The frontier model performs complex reasoning (as it already does inside
  Project 1's `propose_fix`).
- JEV provides narrow, bounded judgments only — classifications, scores, or
  similarly constrained outputs at specific decision points. It does not run
  jobs, does not choose actions, and does not persist state.
- Deterministic Python retains authority over all state transitions and all
  permitted actions. Every decision JEV or the frontier model feeds into is
  ultimately gated by explicit Python policy code.
- Prefer explicit Python over orchestration frameworks.
- Do not introduce LangChain, LangGraph, Celery, Kafka, Temporal, Kubernetes,
  or any generic workflow engine. (Note: `langgraph`, `langchain-anthropic`,
  and `langchain-ollama` currently sit unused in `pyproject.toml` from earlier
  exploration — Project 2 must not start using them; removing them is a
  separate, later cleanup, not part of this SDD setup.)

## Non-goals for v1

- Concurrent job execution / multiple workers.
- Distributed or multi-machine durability (a local SQLite store is
  sufficient — see `architecture.md`).
- Authentication, authorization, or multi-tenant access to the console.
- Generalizing beyond the FleetOps workload — Project 2 governs the existing
  Project 1 pipeline, it does not become a general-purpose job runner for
  arbitrary tasks.
- Replacing `python -m ase.main` (it remains the raw, ungoverned Project 1
  demo path — see `roadmap.md`).
- Production-grade crash consistency guarantees beyond "resume correctly from
  the last committed checkpoint in the common case."
