# Validation — Milestone 3: JEV judgment

How to know this milestone is done and mergeable. Mirrors the roadmap's
Milestone 3 exit criteria: "the retry/escalate decision on a `VERIFY` failure
visibly consults a real JEV judgment, and the deterministic policy — not JEV
— remains the thing that actually sets the job's next state."

## Automated checks (must all pass)

```powershell
python -m pytest -q
python -m ruff check src/ase tests/ase target/fleetops src/jev_agent tests/jev_agent
python -m mypy src/ase target/fleetops src/jev_agent
```

Automated tests use a fake `judge_fn`; none may require network access or a
TypeSafe key.

## Specific behaviors to confirm (via tests, per `plan.md` sections 2-4)

1. **Retry cap still wins.** At `retry_count >= MAX_VERIFY_RETRIES`, policy
   returns `FAIL` even for a confident `RETRYABLE` judgment.
2. **Confident `NOT_RETRYABLE` fails early.** Job ends `FAILED` after a
   single attempt with `retry_count == 0` — remaining retries are not spent.
3. **Confident `RETRYABLE` behaves like Milestone 2.** Always-failing verify
   still yields 3 attempts then `FAILED`.
4. **Unavailable judgment falls back.** A `judge_fn` that raises does not
   crash or fail the job; the fixed Milestone 2 rule applies and the history
   event records the error.
5. **Low-confidence falls back.** A judgment below `MIN_JUDGMENT_CONFIDENCE`
   is handled like an unavailable one; the boundary is unit-tested.
6. **Policy, not JEV, sets state.** Job status and `retry_count` in every
   test match the `StepOutcome` from `policy.py`; `judgment.py` has no access
   to the store and is never given the ability to change job state.
7. **History records every judgment.** Exactly one `JEV_JUDGMENT` event per
   `VERIFY` failure, holding input, output (or error), and the decided
   outcome, written before the outcome is acted on; readable via
   `store.list_history`.
8. **History is append-only and job-scoped.** Store tests cover ordering,
   round-tripping of payload, and isolation between jobs.
9. **No regression.** Milestone 1 and 2 behaviors (resume at the correct
   step, attempt-aware recovery, `PROPOSE`/`APPLY` failures immediately
   `FAILED`, no double-apply) still pass.
10. **Policy stays pure.** `decide_verify_failure_outcome` has direct unit
    coverage independent of the runner.

## Manual live demo (required before merge)

Requires `TYPESAFE_API_KEY` and `ANTHROPIC_API_KEY` in the environment.

1. Run `jev_agent/demo_judgment.py` against
   `S02-unsupported-patch-fields` with the forced-failure `verify_fn` and the
   **real** JEV judge.
2. Confirm console output shows, for at least one `VERIFY` failure: a real
   JEV label and confidence, the outcome policy chose, and the resulting job
   status.
3. Confirm the printed `execution_history` (read back from `jev_agent.db`)
   contains a `JEV_JUDGMENT` event with the state sent to JEV, its answer,
   and the policy outcome.
4. Confirm the final status is consistent with policy rules (bounded by the
   retry cap; early `FAILED` if JEV was confident `NOT_RETRYABLE`).

As in Milestone 2, a real `PROPOSE` call in a later attempt can fail on its
own (Project 1 behavior, out of bounds to change) and end the live demo
early. That is not a Milestone 3 defect; the deterministic paths are proven
by the fake-judge tests. The live run's job is to prove the real SDK wiring
works end to end. Record the actual run (date, labels/confidences seen,
final status) in this file when done.

**Actual run (2026-09-29, realistic failure text):** job
`09f0d744-0dcc-44a3-bad8-c981b6c9daaf`, S02 with `bug.patch` injected and a forced
VERIFY failure carrying real pytest output (`DID NOT RAISE ValueError`).

| Attempt | Real JEV answer | Policy decision | Why |
| --- | --- | --- | --- |
| 1 | `retryable`, 0.99 | `RETRY` | Confident judgment, under the cap: followed. |
| 2 | `not_retryable`, 0.19 | `RETRY` | Below `MIN_JUDGMENT_CONFIDENCE` (0.5): judgment ignored, fixed-rule fallback. |
| 3 | not consulted | `FAILED` | `PROPOSE` raised `RuntimeError: Claude did not converge within 30 tool turns`, recorded as a `STEP_ERROR`. |

Final status `FAILED`, `retry_count == 2` (`MAX_VERIFY_RETRIES`). Each
`JEV_JUDGMENT` event holds the state sent, JEV's answer, and the outcome
policy decided, and `target/fleetops` was restored to baseline afterward.
This shows, live: a real judgment consulted and recorded on each VERIFY
failure; a confident judgment consumed by policy; a low-confidence judgment
overridden by the deterministic fallback; and step errors made diagnosable.

Not shown live: a *confident* `not_retryable` causing an early `FAIL`. That
path is covered by the fake-judge tests (`test_confident_not_retryable_fails_after_one_attempt`).
Note attempt 2's `not_retryable` was arguably the right call (the same failure
recurring), but at 0.19 confidence policy did not act on it; whether 0.5 is
the right `MIN_JUDGMENT_CONFIDENCE` should be tuned on more data.

Why attempts 2 and 3 do not behave like real retries: a retry restarts from
`PROPOSE` on the tree the previous attempt already repaired (Milestone 2's
decision), and the forced failure is fake, so no bug remains to find. This is
a demo artifact, not an M3 defect. Whether a retry should first roll back the
failed attempt's `APPLY` (`apply_fix` returns the previous file content) is
an open design question for Milestone 4.

## Definition of done

- All automated checks pass.
- Behaviors 1-10 have passing tests in `tests/jev_agent/`.
- The manual live demo has been run at least once with a real JEV judgment
  recorded in `execution_history`, and the run is noted above.
- `typesafe-sdk` is the only dependency added; no forbidden frameworks.
- No changes to `src/ase/`, `target/fleetops/`, or `scenarios/S01-*`, other than
  the approved `MAX_TOKENS` / `MAX_TOOL_TURNS` edits in `src/ase/agent.py` (see
  `requirements.md`).
- `specs/roadmap.md` Milestone 3 is marked complete.
