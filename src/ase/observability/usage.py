from dataclasses import dataclass
from typing import (
    Protocol,
    runtime_checkable,
)

from langchain_core.messages import AIMessage


@dataclass(frozen=True, slots=True)
class ModelUsageSnapshot:
    api_calls: int
    calls_with_usage: int
    input_tokens: int
    output_tokens: int


@dataclass
class ModelUsage:
    api_calls: int = 0
    calls_with_usage: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def record(
        self,
        message: AIMessage,
    ) -> None:
        self.api_calls += 1

        metadata = (
            message.usage_metadata
            or {}
        )

        if not metadata:
            return

        self.calls_with_usage += 1

        self.input_tokens += int(
            metadata.get(
                "input_tokens",
                0,
            )
        )

        self.output_tokens += int(
            metadata.get(
                "output_tokens",
                0,
            )
        )

    def snapshot(
        self,
    ) -> ModelUsageSnapshot:
        return ModelUsageSnapshot(
            api_calls=self.api_calls,
            calls_with_usage=(
                self.calls_with_usage
            ),
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
        )


@runtime_checkable
class SupportsModelTelemetry(Protocol):
    @property
    def provider_name(self) -> str:
        ...

    @property
    def model_name(self) -> str:
        ...

    def reset_usage(self) -> None:
        ...

    def usage_snapshot(
        self,
    ) -> ModelUsageSnapshot:
        ...
