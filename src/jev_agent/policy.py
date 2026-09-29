from enum import StrEnum

from jev_agent.models import Judgment, Retryability

MAX_VERIFY_RETRIES = 2
MIN_JUDGMENT_CONFIDENCE = 0.5


class StepOutcome(StrEnum):
    """The closed set of outcomes deterministic policy can decide.

    `ESCALATE` is part of this type now so later milestones don't need a
    breaking rename, but it isn't reachable yet: budgets and escalation
    arrive in Milestone 4, so a `VERIFY` failure only ever resolves to
    `RETRY` or `FAIL`.
    """

    RETRY = "retry"
    FAIL = "fail"
    ESCALATE = "escalate"


def decide_verify_failure_outcome(retry_count: int, judgment: Judgment | None) -> StepOutcome:
    """Decide what to do after a `VERIFY` step reports failure.

    Pure and deterministic: no I/O, no side effects. `judgment` is a JEV
    classification (or `None` if it was unavailable); it is one input, never
    the decision. Rules, in order:

    1. Retry cap reached -> `FAIL`, whatever the judgment says.
    2. No judgment, or confidence below `MIN_JUDGMENT_CONFIDENCE` -> the
       fixed rule: `RETRY` while under the cap.
    3. Confident `NOT_RETRYABLE` -> `FAIL` early.
    4. Confident `RETRYABLE` -> `RETRY`.

    Milestone 4 remaps the fallback and the early failure to `ESCALATE`.
    """
    if retry_count >= MAX_VERIFY_RETRIES:
        return StepOutcome.FAIL
    if judgment is None or judgment.confidence < MIN_JUDGMENT_CONFIDENCE:
        return StepOutcome.RETRY
    if judgment.retryability is Retryability.NOT_RETRYABLE:
        return StepOutcome.FAIL
    return StepOutcome.RETRY
