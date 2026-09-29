import pytest

from jev_agent.models import Judgment, Retryability
from jev_agent.policy import (
    MAX_VERIFY_RETRIES,
    MIN_JUDGMENT_CONFIDENCE,
    StepOutcome,
    decide_verify_failure_outcome,
)

HIGH = 0.95
LOW = MIN_JUDGMENT_CONFIDENCE - 0.01


def _judgment(retryability: Retryability, confidence: float) -> Judgment:
    return Judgment(retryability=retryability, confidence=confidence)


@pytest.mark.parametrize("retry_count", range(MAX_VERIFY_RETRIES))
def test_no_judgment_retries_below_the_cap(retry_count: int) -> None:
    assert decide_verify_failure_outcome(retry_count, None) is StepOutcome.RETRY


@pytest.mark.parametrize("retry_count", [MAX_VERIFY_RETRIES, MAX_VERIFY_RETRIES + 5])
def test_no_judgment_fails_at_and_past_the_cap(retry_count: int) -> None:
    assert decide_verify_failure_outcome(retry_count, None) is StepOutcome.FAIL


@pytest.mark.parametrize("retry_count", [MAX_VERIFY_RETRIES, MAX_VERIFY_RETRIES + 5])
def test_cap_wins_over_a_confident_retryable_judgment(retry_count: int) -> None:
    judgment = _judgment(Retryability.RETRYABLE, HIGH)
    assert decide_verify_failure_outcome(retry_count, judgment) is StepOutcome.FAIL


@pytest.mark.parametrize("retry_count", range(MAX_VERIFY_RETRIES))
def test_confident_retryable_retries_below_the_cap(retry_count: int) -> None:
    judgment = _judgment(Retryability.RETRYABLE, HIGH)
    assert decide_verify_failure_outcome(retry_count, judgment) is StepOutcome.RETRY


@pytest.mark.parametrize("retry_count", range(MAX_VERIFY_RETRIES))
def test_confident_not_retryable_fails_early(retry_count: int) -> None:
    judgment = _judgment(Retryability.NOT_RETRYABLE, HIGH)
    assert decide_verify_failure_outcome(retry_count, judgment) is StepOutcome.FAIL


@pytest.mark.parametrize("retryability", list(Retryability))
def test_low_confidence_falls_back_to_the_fixed_rule(retryability: Retryability) -> None:
    judgment = _judgment(retryability, LOW)
    assert decide_verify_failure_outcome(0, judgment) is StepOutcome.RETRY
    assert decide_verify_failure_outcome(MAX_VERIFY_RETRIES, judgment) is StepOutcome.FAIL


def test_confidence_boundary_is_inclusive_of_the_minimum() -> None:
    at_minimum = _judgment(Retryability.NOT_RETRYABLE, MIN_JUDGMENT_CONFIDENCE)
    assert decide_verify_failure_outcome(0, at_minimum) is StepOutcome.FAIL
    below = _judgment(Retryability.NOT_RETRYABLE, LOW)
    assert decide_verify_failure_outcome(0, below) is StepOutcome.RETRY


def test_decision_is_a_pure_function_of_its_inputs() -> None:
    judgment = _judgment(Retryability.NOT_RETRYABLE, HIGH)
    assert decide_verify_failure_outcome(0, judgment) == decide_verify_failure_outcome(0, judgment)
