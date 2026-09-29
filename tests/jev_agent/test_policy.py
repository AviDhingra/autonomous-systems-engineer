import pytest

from jev_agent.models import Budget, EscalationReason, Judgment, Retryability
from jev_agent.policy import (
    MIN_JUDGMENT_CONFIDENCE,
    StepOutcome,
    budget_exceeded,
    decide_verify_failure_outcome,
    wall_clock_exceeded,
)

HIGH = 0.95
LOW = MIN_JUDGMENT_CONFIDENCE - 0.01
BUDGET = Budget(max_retries=2, max_wall_clock_seconds=100.0)
UNDER_TIME = 10.0
OVER_TIME = 1000.0


def _judgment(retryability: Retryability, confidence: float) -> Judgment:
    return Judgment(retryability=retryability, confidence=confidence)


def _decide(
    retry_count: int, judgment: Judgment | None, elapsed: float = UNDER_TIME
) -> StepOutcome:
    return decide_verify_failure_outcome(retry_count, judgment, BUDGET, elapsed)


# --- budget_exceeded ---


def test_no_budget_exceeded_below_both_limits() -> None:
    assert budget_exceeded(BUDGET.max_retries - 1, UNDER_TIME, BUDGET) is None


@pytest.mark.parametrize("retry_count", [BUDGET.max_retries, BUDGET.max_retries + 5])
def test_retry_budget_exhausted_at_and_past_the_limit(retry_count: int) -> None:
    assert (
        budget_exceeded(retry_count, UNDER_TIME, BUDGET) is EscalationReason.RETRY_BUDGET_EXHAUSTED
    )


def test_wall_clock_boundary_is_at_the_limit() -> None:
    just_under = BUDGET.max_wall_clock_seconds - 0.001
    assert not wall_clock_exceeded(just_under, BUDGET)
    assert wall_clock_exceeded(BUDGET.max_wall_clock_seconds, BUDGET)
    assert budget_exceeded(0, just_under, BUDGET) is None
    assert (
        budget_exceeded(0, BUDGET.max_wall_clock_seconds, BUDGET)
        is EscalationReason.WALL_CLOCK_EXCEEDED
    )


def test_retry_budget_is_reported_first_when_both_are_exceeded() -> None:
    assert (
        budget_exceeded(BUDGET.max_retries, OVER_TIME, BUDGET)
        is EscalationReason.RETRY_BUDGET_EXHAUSTED
    )


def test_zero_retry_budget_is_exceeded_immediately() -> None:
    zero = Budget(max_retries=0, max_wall_clock_seconds=100.0)
    assert budget_exceeded(0, UNDER_TIME, zero) is EscalationReason.RETRY_BUDGET_EXHAUSTED


# --- decide_verify_failure_outcome ---


@pytest.mark.parametrize("retry_count", range(BUDGET.max_retries))
def test_no_judgment_retries_under_budget(retry_count: int) -> None:
    assert _decide(retry_count, None) is StepOutcome.RETRY


@pytest.mark.parametrize("retry_count", [BUDGET.max_retries, BUDGET.max_retries + 5])
def test_no_judgment_escalates_when_retries_are_exhausted(retry_count: int) -> None:
    assert _decide(retry_count, None) is StepOutcome.ESCALATE


def test_no_judgment_escalates_when_wall_clock_is_exceeded() -> None:
    assert _decide(0, None, OVER_TIME) is StepOutcome.ESCALATE


@pytest.mark.parametrize("retry_count", [0, BUDGET.max_retries])
def test_budget_wins_over_a_confident_retryable_judgment(retry_count: int) -> None:
    judgment = _judgment(Retryability.RETRYABLE, HIGH)
    elapsed = OVER_TIME if retry_count == 0 else UNDER_TIME
    assert _decide(retry_count, judgment, elapsed) is StepOutcome.ESCALATE


@pytest.mark.parametrize("retry_count", range(BUDGET.max_retries))
def test_confident_retryable_retries_under_budget(retry_count: int) -> None:
    assert _decide(retry_count, _judgment(Retryability.RETRYABLE, HIGH)) is StepOutcome.RETRY


@pytest.mark.parametrize("retry_count", range(BUDGET.max_retries))
def test_confident_not_retryable_escalates(retry_count: int) -> None:
    judgment = _judgment(Retryability.NOT_RETRYABLE, HIGH)
    assert _decide(retry_count, judgment) is StepOutcome.ESCALATE


@pytest.mark.parametrize("retryability", list(Retryability))
def test_low_confidence_falls_back_to_the_fixed_rule(retryability: Retryability) -> None:
    judgment = _judgment(retryability, LOW)
    assert _decide(0, judgment) is StepOutcome.RETRY
    assert _decide(BUDGET.max_retries, judgment) is StepOutcome.ESCALATE


def test_confidence_boundary_is_inclusive_of_the_minimum() -> None:
    at_minimum = _judgment(Retryability.NOT_RETRYABLE, MIN_JUDGMENT_CONFIDENCE)
    assert _decide(0, at_minimum) is StepOutcome.ESCALATE
    below = _judgment(Retryability.NOT_RETRYABLE, LOW)
    assert _decide(0, below) is StepOutcome.RETRY


def test_verify_failure_never_decides_fail() -> None:
    for retry_count in range(BUDGET.max_retries + 3):
        for judgment in (None, _judgment(Retryability.RETRYABLE, HIGH)):
            for elapsed in (UNDER_TIME, OVER_TIME):
                assert _decide(retry_count, judgment, elapsed) is not StepOutcome.FAIL


def test_decision_is_a_pure_function_of_its_inputs() -> None:
    judgment = _judgment(Retryability.NOT_RETRYABLE, HIGH)
    assert _decide(0, judgment) == _decide(0, judgment)
