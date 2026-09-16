import pytest

from ase.providers.settings import (
    ModelSettings,
)


def test_anthropic_is_default_provider(
    monkeypatch,
) -> None:
    monkeypatch.delenv(
        "ASE_PROVIDER",
        raising=False,
    )
    monkeypatch.delenv(
        "ASE_MODEL",
        raising=False,
    )

    settings = (
        ModelSettings.from_environment()
    )

    assert settings.provider == "anthropic"
    assert settings.model == "claude-sonnet-5"
    assert settings.ollama_base_url is None


def test_ollama_keeps_optional_base_url(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "ASE_PROVIDER",
        "ollama",
    )
    monkeypatch.delenv(
        "ASE_MODEL",
        raising=False,
    )

    settings = (
        ModelSettings.from_environment()
    )

    assert settings.provider == "ollama"
    assert settings.model == "qwen3-coder:latest"
    assert settings.ollama_base_url


def test_unknown_provider_is_rejected(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "ASE_PROVIDER",
        "made-up-provider",
    )

    with pytest.raises(
        ValueError,
        match="Unsupported ASE_PROVIDER",
    ):
        ModelSettings.from_environment()
