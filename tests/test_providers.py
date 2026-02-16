"""Unit tests for provider kwargs resolution.

Purpose:
    Test API key and base URL resolution for all LLM providers.

Responsibilities:
    - Verify correct kwargs returned for each provider
    - Verify ValueError raised for missing required config
    - Verify case-insensitive model prefix matching
    - Verify API key isolation between providers

Non-scope:
    - Actual API calls (mocked settings used)
    - Integration tests with real litellm
"""

from typing import Callable

import pytest

from cloop.providers import resolve_provider_kwargs
from cloop.settings import Settings


class TestOllamaProvider:
    """Tests for ollama/ model prefix handling."""

    def test_raises_when_api_base_missing(self, test_settings: Callable[..., Settings]) -> None:
        """Ollama requires CLOOP_OLLAMA_API_BASE to be set."""
        settings = test_settings(ollama_api_base=None)
        with pytest.raises(ValueError, match="ollama/.*requires.*CLOOP_OLLAMA_API_BASE"):
            resolve_provider_kwargs("ollama/llama3", settings)

    def test_returns_api_base_when_configured(self, test_settings: Callable[..., Settings]) -> None:
        """Returns api_base in kwargs when OLLAMA_API_BASE is set."""
        settings = test_settings(ollama_api_base="http://localhost:11434/v1")
        result = resolve_provider_kwargs("ollama/llama3", settings)
        assert result == {"api_base": "http://localhost:11434/v1"}

    def test_case_insensitive_OLLAMA_prefix(self, test_settings: Callable[..., Settings]) -> None:
        """Model prefix matching is case-insensitive."""
        settings = test_settings(ollama_api_base="http://localhost:11434/v1")
        result = resolve_provider_kwargs("OLLAMA/llama3", settings)
        assert result == {"api_base": "http://localhost:11434/v1"}

    def test_no_api_key_in_kwargs(self, test_settings: Callable[..., Settings]) -> None:
        """Ollama never includes api_key in kwargs."""
        settings = test_settings(ollama_api_base="http://localhost:11434/v1")
        result = resolve_provider_kwargs("ollama/llama3", settings)
        assert "api_key" not in result


class TestGeminiProvider:
    """Tests for gemini/ and google/ model prefix handling."""

    def test_raises_when_api_key_missing(self, test_settings: Callable[..., Settings]) -> None:
        """Gemini requires CLOOP_GOOGLE_API_KEY or LITELLM_API_KEY."""
        settings = test_settings(google_api_key=None)
        with pytest.raises(ValueError, match="Gemini model requires.*CLOOP_GOOGLE_API_KEY"):
            resolve_provider_kwargs("gemini/gemini-pro", settings)

    def test_returns_api_key_with_gemini_prefix(
        self, test_settings: Callable[..., Settings]
    ) -> None:
        """Returns api_key for gemini/ prefix."""
        settings = test_settings(google_api_key="test-gemini-key")
        result = resolve_provider_kwargs("gemini/gemini-pro", settings)
        assert result == {"api_key": "test-gemini-key"}

    def test_returns_api_key_with_google_prefix(
        self, test_settings: Callable[..., Settings]
    ) -> None:
        """Returns api_key for google/ prefix (alias)."""
        settings = test_settings(google_api_key="test-google-key")
        result = resolve_provider_kwargs("google/gemini-pro", settings)
        assert result == {"api_key": "test-google-key"}

    def test_case_insensitive_gemini_prefix(self, test_settings: Callable[..., Settings]) -> None:
        """Model prefix matching is case-insensitive."""
        settings = test_settings(google_api_key="test-key")
        result = resolve_provider_kwargs("GEMINI/gemini-pro", settings)
        assert result == {"api_key": "test-key"}

    def test_case_insensitive_google_prefix(self, test_settings: Callable[..., Settings]) -> None:
        """Model prefix matching is case-insensitive for google/ alias."""
        settings = test_settings(google_api_key="test-key")
        result = resolve_provider_kwargs("GOOGLE/gemini-pro", settings)
        assert result == {"api_key": "test-key"}

    def test_no_api_base_in_kwargs(self, test_settings: Callable[..., Settings]) -> None:
        """Gemini never includes api_base in kwargs (uses litellm defaults)."""
        settings = test_settings(google_api_key="test-key")
        result = resolve_provider_kwargs("gemini/gemini-pro", settings)
        assert "api_base" not in result


class TestOpenAIProvider:
    """Tests for openai/, gpt-, and o1- model prefix handling."""

    def test_raises_when_api_key_missing(self, test_settings: Callable[..., Settings]) -> None:
        """OpenAI requires CLOOP_OPENAI_API_KEY."""
        settings = test_settings(openai_api_key=None)
        with pytest.raises(ValueError, match="OpenAI model requires.*CLOOP_OPENAI_API_KEY"):
            resolve_provider_kwargs("openai/gpt-4", settings)

    def test_returns_api_key_with_openai_prefix(
        self, test_settings: Callable[..., Settings]
    ) -> None:
        """Returns api_key for openai/ prefix."""
        settings = test_settings(openai_api_key="sk-test-key")
        result = resolve_provider_kwargs("openai/gpt-4", settings)
        assert result == {"api_key": "sk-test-key"}

    def test_returns_api_key_with_gpt_prefix(self, test_settings: Callable[..., Settings]) -> None:
        """Returns api_key for gpt- prefix (e.g., gpt-4o-mini)."""
        settings = test_settings(openai_api_key="sk-test-key")
        result = resolve_provider_kwargs("gpt-4o-mini", settings)
        assert result == {"api_key": "sk-test-key"}

    def test_returns_api_key_with_o1_prefix(self, test_settings: Callable[..., Settings]) -> None:
        """Returns api_key for o1- prefix (reasoning models)."""
        settings = test_settings(openai_api_key="sk-test-key")
        result = resolve_provider_kwargs("o1-preview", settings)
        assert result == {"api_key": "sk-test-key"}

    def test_includes_api_base_when_configured(
        self, test_settings: Callable[..., Settings]
    ) -> None:
        """Includes api_base when OPENAI_API_BASE is set."""
        settings = test_settings(
            openai_api_key="sk-test-key",
            openai_api_base="https://custom.openai/v1",
        )
        result = resolve_provider_kwargs("openai/gpt-4", settings)
        assert result == {
            "api_key": "sk-test-key",
            "api_base": "https://custom.openai/v1",
        }

    def test_case_insensitive_openai_prefix(self, test_settings: Callable[..., Settings]) -> None:
        """Model prefix matching is case-insensitive."""
        settings = test_settings(openai_api_key="sk-test-key")
        result = resolve_provider_kwargs("OPENAI/gpt-4", settings)
        assert result == {"api_key": "sk-test-key"}

    def test_case_insensitive_gpt_prefix(self, test_settings: Callable[..., Settings]) -> None:
        """GPT prefix matching is case-insensitive."""
        settings = test_settings(openai_api_key="sk-test-key")
        result = resolve_provider_kwargs("GPT-4o-mini", settings)
        assert result == {"api_key": "sk-test-key"}

    def test_case_insensitive_o1_prefix(self, test_settings: Callable[..., Settings]) -> None:
        """O1 prefix matching is case-insensitive."""
        settings = test_settings(openai_api_key="sk-test-key")
        result = resolve_provider_kwargs("O1-preview", settings)
        assert result == {"api_key": "sk-test-key"}

    def test_gpt4_prefix_detected(self, test_settings: Callable[..., Settings]) -> None:
        """gpt-4 prefix is detected correctly."""
        settings = test_settings(openai_api_key="sk-test-key")
        result = resolve_provider_kwargs("gpt-4", settings)
        assert result == {"api_key": "sk-test-key"}

    def test_gpt35_prefix_detected(self, test_settings: Callable[..., Settings]) -> None:
        """gpt-3.5 prefix is detected correctly."""
        settings = test_settings(openai_api_key="sk-test-key")
        result = resolve_provider_kwargs("gpt-3.5-turbo", settings)
        assert result == {"api_key": "sk-test-key"}

    def test_o1_mini_detected(self, test_settings: Callable[..., Settings]) -> None:
        """o1-mini is detected correctly."""
        settings = test_settings(openai_api_key="sk-test-key")
        result = resolve_provider_kwargs("o1-mini", settings)
        assert result == {"api_key": "sk-test-key"}

    def test_no_api_base_when_not_configured(self, test_settings: Callable[..., Settings]) -> None:
        """api_base is not included when OPENAI_API_BASE is not set."""
        settings = test_settings(
            openai_api_key="sk-test-key",
            openai_api_base=None,
        )
        result = resolve_provider_kwargs("openai/gpt-4", settings)
        assert "api_base" not in result


class TestLMStudioProvider:
    """Tests for lmstudio/ model prefix handling."""

    def test_returns_empty_kwargs_when_no_api_base(
        self, test_settings: Callable[..., Settings]
    ) -> None:
        """LM Studio works without api_base (uses defaults)."""
        settings = test_settings(lmstudio_api_base=None)
        result = resolve_provider_kwargs("lmstudio/llama3", settings)
        assert result == {}

    def test_returns_api_base_when_configured(self, test_settings: Callable[..., Settings]) -> None:
        """Returns api_base when LMSTUDIO_API_BASE is set."""
        settings = test_settings(lmstudio_api_base="http://localhost:1234/v1")
        result = resolve_provider_kwargs("lmstudio/llama3", settings)
        assert result == {"api_base": "http://localhost:1234/v1"}

    def test_case_insensitive_prefix(self, test_settings: Callable[..., Settings]) -> None:
        """Model prefix matching is case-insensitive."""
        settings = test_settings(lmstudio_api_base="http://localhost:1234/v1")
        result = resolve_provider_kwargs("LMSTUDIO/llama3", settings)
        assert result == {"api_base": "http://localhost:1234/v1"}

    def test_no_api_key_in_kwargs(self, test_settings: Callable[..., Settings]) -> None:
        """LM Studio never includes api_key in kwargs."""
        settings = test_settings(lmstudio_api_base="http://localhost:1234/v1")
        result = resolve_provider_kwargs("lmstudio/llama3", settings)
        assert "api_key" not in result


class TestOpenRouterProvider:
    """Tests for openrouter/ model prefix handling."""

    def test_returns_empty_kwargs_when_no_api_base(
        self, test_settings: Callable[..., Settings]
    ) -> None:
        """OpenRouter works without custom api_base."""
        settings = test_settings(openrouter_api_base=None)
        result = resolve_provider_kwargs("openrouter/anthropic/claude-3", settings)
        assert result == {}

    def test_returns_api_base_when_configured(self, test_settings: Callable[..., Settings]) -> None:
        """Returns api_base when OPENROUTER_API_BASE is set."""
        settings = test_settings(openrouter_api_base="https://openrouter.ai/api/v1")
        result = resolve_provider_kwargs("openrouter/anthropic/claude-3", settings)
        assert result == {"api_base": "https://openrouter.ai/api/v1"}

    def test_case_insensitive_prefix(self, test_settings: Callable[..., Settings]) -> None:
        """Model prefix matching is case-insensitive."""
        settings = test_settings(openrouter_api_base="https://openrouter.ai/api/v1")
        result = resolve_provider_kwargs("OPENROUTER/anthropic/claude-3", settings)
        assert result == {"api_base": "https://openrouter.ai/api/v1"}

    def test_no_api_key_in_kwargs(self, test_settings: Callable[..., Settings]) -> None:
        """OpenRouter uses api_base only, no api_key in kwargs."""
        settings = test_settings(openrouter_api_base="https://openrouter.ai/api/v1")
        result = resolve_provider_kwargs("openrouter/anthropic/claude-3", settings)
        assert "api_key" not in result


class TestUnknownModels:
    """Tests for unknown/unsupported model prefixes."""

    def test_returns_empty_kwargs_for_unknown_prefix(
        self, test_settings: Callable[..., Settings]
    ) -> None:
        """Unknown prefixes return empty kwargs (passthrough to litellm)."""
        settings = test_settings()
        result = resolve_provider_kwargs("unknown/model", settings)
        assert result == {}

    def test_returns_empty_kwargs_for_bare_model(
        self, test_settings: Callable[..., Settings]
    ) -> None:
        """Bare model names without prefix return empty kwargs."""
        settings = test_settings()
        result = resolve_provider_kwargs("llama3", settings)
        assert result == {}

    def test_no_provider_specific_fields_leaked(
        self, test_settings: Callable[..., Settings]
    ) -> None:
        """Unknown models don't get any provider-specific kwargs."""
        settings = test_settings(
            ollama_api_base="http://ollama:11434",
            openai_api_key="sk-openai",
            google_api_key="google-key",
        )
        result = resolve_provider_kwargs("unknown/model", settings)
        assert result == {}


class TestProviderIsolation:
    """Security tests ensuring API keys don't leak between providers."""

    def test_ollama_does_not_get_openai_key(self, test_settings: Callable[..., Settings]) -> None:
        """Ollama models must not receive OpenAI API key."""
        settings = test_settings(
            ollama_api_base="http://localhost:11434/v1",
            openai_api_key="sk-secret-openai-key",
        )
        result = resolve_provider_kwargs("ollama/llama3", settings)
        assert "api_key" not in result

    def test_ollama_does_not_get_gemini_key(self, test_settings: Callable[..., Settings]) -> None:
        """Ollama models must not receive Gemini API key."""
        settings = test_settings(
            ollama_api_base="http://localhost:11434/v1",
            google_api_key="secret-gemini-key",
        )
        result = resolve_provider_kwargs("ollama/llama3", settings)
        assert "api_key" not in result

    def test_gemini_does_not_get_openai_key(self, test_settings: Callable[..., Settings]) -> None:
        """Gemini models must not receive OpenAI API key."""
        settings = test_settings(
            google_api_key="gemini-key",
            openai_api_key="sk-secret-openai-key",
        )
        result = resolve_provider_kwargs("gemini/gemini-pro", settings)
        assert result == {"api_key": "gemini-key"}

    def test_openai_does_not_get_gemini_key(self, test_settings: Callable[..., Settings]) -> None:
        """OpenAI models must not receive Gemini API key."""
        settings = test_settings(
            openai_api_key="sk-openai-key",
            google_api_key="secret-gemini-key",
        )
        result = resolve_provider_kwargs("openai/gpt-4", settings)
        assert result == {"api_key": "sk-openai-key"}

    def test_lmstudio_does_not_get_any_keys(self, test_settings: Callable[..., Settings]) -> None:
        """LM Studio must not receive any API keys."""
        settings = test_settings(
            lmstudio_api_base="http://localhost:1234/v1",
            openai_api_key="sk-openai",
            google_api_key="gemini-key",
        )
        result = resolve_provider_kwargs("lmstudio/llama3", settings)
        assert "api_key" not in result
