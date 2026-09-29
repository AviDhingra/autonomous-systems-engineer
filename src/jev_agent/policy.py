from enum import StrEnum

from jev_agent.models import Budget, EscalationReason, Judgment, Retryability

MIN_JUDGMENT_CONFIDENCE = 0.5


class StepOutcome(StrEnum):
    """The closed set of outcomes deterministic policy can decide.

    A `VERIFY` failure resolves to `RETRY` or `ESCALATE`. `FAIL` stays in the
    type for completeness, but a `VERIFY` failure never reaches it: `FAILED`
    is reserved for step exceptions, which the runner records directly.
    """

    RETRY = "retry"
    FAIL = "fail"
    ESCALATE = "escalate"


def wall_clock_exceeded(elapsed_seconds: float, budget: Budget) -> bool:
    return elapsed_seconds >= budget.max_wall_clock_seconds


def budget_exceeded(
    retry_count: int, elapsed_seconds: float, budget: Budget
) -> EscalationReason | None:
    """Which budget, if any, is spent. The retry budget is reported first so
    the reason is deterministic when both are exceeded."""
    if retry_count >= budget.max_retries:
        return EscalationReason.RETRY_BUDGET_EXHAUSTED
    if wall_clock_exceeded(elapsed_seconds, budget):
        return EscalationReason.WALL_CLOCK_EXCEEDED
    return None


def decide_verify_failure_outcome(
    retry_count: int,
    judgment: Judgment | None,
    budget: Budget,
    elapsed_seconds: float,
) -> StepOutcome:
    """Decide what to do after a `VERIFY` step reports failure.

    Pure and deterministic: no I/O, no clock, no side effects. `judgment` is a
    JEV classification (or `None` if it was unavailable); it is one input,
    never the decision. Rules, in order:

    1. Any budget exceeded -> `ESCALATE`, whatever the judgment says.
    2. No judgment, or confidence below `MIN_JUDGMENT_CONFIDENCE` -> `RETRY`
       (the fixed rule: retry while under budget).
    3. Confident `NOT_RETRYABLE` -> `ESCALATE`.
    4. Confident `RETRYABLE` -> `RETRY`.
    """
    if budget_exceeded(retry_count, elapsed_seconds, budget) is not None:
        return StepOutcome.ESCALATE
    if judgment is None or judgment.confidence < MIN_JUDGMENT_CONFIDENCE:
        return StepOutcome.RETRY
    if judgment.retryability is Retryability.NOT_RETRYABLE:
        return StepOutcome.ESCALATE
    return StepOutcome.RETRY
