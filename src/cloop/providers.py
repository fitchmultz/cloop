"""LLM provider configuration resolution.

Purpose:
    Resolve provider-specific kwargs (api_base, api_key) for litellm calls.

Responsibilities:
    - Map model prefixes (ollama/, gemini/, openai/) to provider settings
    - Validate required configuration for each provider
    - Raise clear errors for missing configuration

Non-scope:
    - Model selection logic (caller's responsibility)
    - Actual API calls (see llm.py, embeddings.py)

Entrypoint:
    - resolve_provider_kwargs(model, settings) -> Dict[str, Any]
"""

from typing import Any, Dict

from .settings import Settings


def resolve_provider_kwargs(model: str, settings: Settings) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {}
    model_lower = model.lower()

    if model_lower.startswith("ollama/") and not settings.ollama_api_base:
        raise ValueError("ollama/... requires CLOOP_OLLAMA_API_BASE")

    if model_lower.startswith(("gemini/", "google/")):
        if not settings.google_api_key:
            raise ValueError("Gemini model requires CLOOP_GOOGLE_API_KEY or LITELLM_API_KEY")
        kwargs["api_key"] = settings.google_api_key

    if model_lower.startswith("ollama/"):
        if settings.ollama_api_base:
            kwargs["api_base"] = settings.ollama_api_base
    elif model_lower.startswith("lmstudio/"):
        if settings.lmstudio_api_base:
            kwargs["api_base"] = settings.lmstudio_api_base
    elif model_lower.startswith("openrouter/"):
        if settings.openrouter_api_base:
            kwargs["api_base"] = settings.openrouter_api_base

    if model_lower.startswith(("openai/", "gpt-", "o1-")):
        if settings.openai_api_base:
            kwargs["api_base"] = settings.openai_api_base
        if not settings.openai_api_key:
            raise ValueError("OpenAI model requires CLOOP_OPENAI_API_KEY")
        if settings.openai_api_key:
            kwargs["api_key"] = settings.openai_api_key

    return kwargs
