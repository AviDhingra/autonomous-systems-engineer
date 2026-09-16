from dataclasses import dataclass
import os


SUPPORTED_PROVIDERS = {
    "anthropic",
    "ollama",
}


@dataclass(
    frozen=True,
    slots=True,
)
class ModelSettings:
    provider: str
    model: str
    max_tool_calls: int
    ollama_base_url: str | None

    @classmethod
    def from_environment(
        cls,
    ) -> "ModelSettings":
        provider = os.getenv(
            "ASE_PROVIDER",
            "anthropic",
        ).lower()

        if provider not in SUPPORTED_PROVIDERS:
            raise ValueError(
                "Unsupported ASE_PROVIDER: "
                f"{provider}"
            )

        default_model = (
            "claude-sonnet-5"
            if provider == "anthropic"
            else "qwen3-coder:latest"
        )

        model = os.getenv(
            "ASE_MODEL",
            default_model,
        )

        max_tool_calls = int(
            os.getenv(
                "ASE_MAX_TOOL_CALLS",
                "10",
            )
        )

        ollama_base_url = None

        if provider == "ollama":
            ollama_base_url = os.getenv(
                "ASE_OLLAMA_BASE_URL",
                "http://localhost:11434",
            )

        return cls(
            provider=provider,
            model=model,
            max_tool_calls=max_tool_calls,
            ollama_base_url=ollama_base_url,
        )
