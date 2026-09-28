from enum import StrEnum

MAX_VERIFY_RETRIES = 2


class StepOutcome(StrEnum):
    """The closed set of outcomes deterministic policy can decide.

    `ESCALATE` is part of this type now so later milestones don't need a
    breaking rename, but it isn't reachable yet: Milestone 2 has no budget
    to exceed (Milestone 4), so a `VERIFY` failure only ever resolves to
    `RETRY` or `FAIL`.
    """

    RETRY = "retry"
    FAIL = "fail"
    ESCALATE = "escalate"


def decide_verify_failure_outcome(retry_count: int) -> StepOutcome:
    """Decide what to do after a `VERIFY` step reports failure.

    Pure and deterministic: no I/O, no side effects. `retry_count` is the
    number of retries already consumed by this job. Milestone 3 extends
    this decision to also take a JEV judgment as input; Milestone 4 adds a
    budget check that can force `ESCALATE`. For now, policy retries up to
    `MAX_VERIFY_RETRIES` times, then fails.
    """
    if retry_count < MAX_VERIFY_RETRIES:
        return StepOutcome.RETRY
    return StepOutcome.FAIL
