"""The one bounded JEV judgment: is a VERIFY failure retryable?

This module only asks the question and returns typed data. It has no access
to the store and cannot change job state; the runner owns fallback when this
raises, and `policy` owns what the answer means for the job.
"""

from typing import cast

from typesafe_sdk import Choice, JSONContent, TypeSafeClient

from jev_agent.models import Judgment, Retryability

MAX_FAILURE_OUTPUT_CHARS = 4000
MAX_PRIOR_FAILURES = 3
QUESTION_ID = "retryability"

_QUESTION = Choice(
    instructions=(
        "A coding agent applied a proposed fix and then ran verification "
        "(pytest, Ruff, mypy), which failed. Decide whether trying again with "
        "a fresh proposal is worthwhile."
    ),
    criteria={
        Retryability.RETRYABLE.value: (
            "The failure is transient, or plausibly fixed by a fresh proposal "
            "(e.g. a specific test or lint error the agent could correct)."
        ),
        Retryability.NOT_RETRYABLE.value: (
            "The same class of failure keeps recurring across attempts, or it "
            "points to a deeper problem that a bounded retry cannot address."
        ),
    },
)


def build_judgment_state(
    failure_output: str, attempt: int, prior_failures: list[str]
) -> dict[str, object]:
    """The exact state sent to JEV; also recorded verbatim in execution history."""
    return {
        "failure_output": failure_output[:MAX_FAILURE_OUTPUT_CHARS],
        "attempt": attempt,
        "prior_failures": [
            output[:MAX_FAILURE_OUTPUT_CHARS] for output in prior_failures[-MAX_PRIOR_FAILURES:]
        ],
    }


def judge_verify_failure(state: dict[str, object]) -> Judgment:
    """Ask JEV whether a VERIFY failure is retryable. Raises on any SDK
    failure or malformed answer; it never swallows errors."""
    with TypeSafeClient() as client:
        response = client.system_one(
            state=cast(JSONContent, state),
            questions={QUESTION_ID: _QUESTION},
        )
    answer = response.choices[QUESTION_ID]
    return Judgment(retryability=Retryability(answer.choice), confidence=answer.confidence)
