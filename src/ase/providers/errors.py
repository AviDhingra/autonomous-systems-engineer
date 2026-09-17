from typing import NoReturn


class AgentRuntimeError(Exception):
    """Base class for expected failures during one model-driven episode."""


class ModelProviderError(AgentRuntimeError):
    """The remote/local model provider did not complete a usable request."""


class ModelAuthenticationError(ModelProviderError):
    """The provider rejected authentication."""


class ModelRateLimitError(ModelProviderError):
    """The provider rejected the request because of quota/rate limits."""


class ModelConnectionError(ModelProviderError):
    """The request could not reach or complete with the provider."""


class ModelOutputError(AgentRuntimeError):
    """The model responded, but its output did not satisfy our runtime contract."""


class ToolBudgetExceeded(AgentRuntimeError):
    """The investigation used more tool calls than the configured maximum."""


def raise_provider_error(
    *,
    provider: str,
    stage: str,
    exc: Exception,
) -> NoReturn:
    """Translate provider-library exceptions into project-level exceptions."""

    if provider == "anthropic":
        import anthropic

        if isinstance(
            exc,
            anthropic.AuthenticationError,
        ):
            raise ModelAuthenticationError(
                f"{stage}: Anthropic authentication failed"
            ) from exc

        if isinstance(
            exc,
            anthropic.RateLimitError,
        ):
            raise ModelRateLimitError(
                f"{stage}: Anthropic rate limit exceeded"
            ) from exc

        if isinstance(
            exc,
            (
                anthropic.APITimeoutError,
                anthropic.APIConnectionError,
            ),
        ):
            raise ModelConnectionError(
                f"{stage}: Anthropic request could not complete"
            ) from exc

    raise ModelProviderError(
        f"{stage}: model provider request failed "
        f"({type(exc).__name__})"
    ) from exc
    