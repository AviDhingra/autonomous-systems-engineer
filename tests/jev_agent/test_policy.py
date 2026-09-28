import pytest

from jev_agent.policy import MAX_VERIFY_RETRIES, StepOutcome, decide_verify_failure_outcome


@pytest.mark.parametrize("retry_count", range(MAX_VERIFY_RETRIES))
def test_retries_below_the_cap(retry_count: int) -> None:
    assert decide_verify_failure_outcome(retry_count) is StepOutcome.RETRY


def test_fails_once_the_cap_is_reached() -> None:
    assert decide_verify_failure_outcome(MAX_VERIFY_RETRIES) is StepOutcome.FAIL


def test_fails_past_the_cap() -> None:
    assert decide_verify_failure_outcome(MAX_VERIFY_RETRIES + 5) is StepOutcome.FAIL


def test_decision_is_a_pure_function_of_retry_count() -> None:
    """Same input, same output — no hidden state, no side effects."""
    assert decide_verify_failure_outcome(0) == decide_verify_failure_outcome(0)
