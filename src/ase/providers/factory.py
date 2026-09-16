from langchain_core.language_models.chat_models import (
    BaseChatModel,
)

from .settings import ModelSettings


def build_chat_model(
    settings: ModelSettings,
) -> BaseChatModel:
    if settings.provider == "anthropic":
        from langchain_anthropic import (
            ChatAnthropic,
        )

        return ChatAnthropic(
            model=settings.model,
            max_tokens=8192,
            max_retries=2,
            timeout=120,
        )

    if settings.provider == "ollama":
        from langchain_ollama import (
            ChatOllama,
        )

        if settings.ollama_base_url is None:
            raise ValueError(
                "Ollama provider requires "
                "ollama_base_url"
            )

        return ChatOllama(
            model=settings.model,
            base_url=(
                settings.ollama_base_url
            ),
            validate_model_on_init=True,
        )

    raise ValueError(
        "Unsupported provider: "
        f"{settings.provider}"
    )
