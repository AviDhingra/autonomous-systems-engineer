from langchain_core.messages import (
    AIMessage,
)

from ase.observability.usage import (
    ModelUsage,
)


def test_model_usage_accumulates_tokens() -> None:
    usage = ModelUsage()

    usage.record(
        AIMessage(
            content="first",
            usage_metadata={
                "input_tokens": 100,
                "output_tokens": 20,
                "total_tokens": 120,
            },
        )
    )

    usage.record(
        AIMessage(
            content="second",
            usage_metadata={
                "input_tokens": 50,
                "output_tokens": 10,
                "total_tokens": 60,
            },
        )
    )

    snapshot = usage.snapshot()

    assert snapshot.api_calls == 2
    assert snapshot.calls_with_usage == 2
    assert snapshot.input_tokens == 150
    assert snapshot.output_tokens == 30


def test_missing_usage_is_not_invented() -> None:
    usage = ModelUsage()

    usage.record(
        AIMessage(
            content="no metadata",
        )
    )

    snapshot = usage.snapshot()

    assert snapshot.api_calls == 1
    assert snapshot.calls_with_usage == 0
    assert snapshot.input_tokens == 0
    assert snapshot.output_tokens == 0
