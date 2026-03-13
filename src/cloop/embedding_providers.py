"""Embedding provider configuration resolution.

Purpose:
    Resolve provider-specific kwargs for the embeddings-only LiteLLM path.

Responsibilities:
    - Map embedding model prefixes to endpoint and credential settings
    - Validate required embedding configuration
    - Keep LiteLLM-specific concerns out of generative runtime modules

Non-scope:
    - Generative pi model selection and auth
    - Embedding API invocation or retry behavior
"""

from typing import Any

from .settings import Settings


def resolve_embedding_provider_kwargs(model: str, settings: Settings) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    model_lower = model.lower()

    if model_lower.startswith("ollama/") and not settings.ollama_api_base:
        raise ValueError("ollama/... requires CLOOP_OLLAMA_API_BASE")

    if model_lower.startswith(("gemini/", "google/")):
        if not settings.google_api_key:
            raise ValueError("Gemini embedding model requires CLOOP_GOOGLE_API_KEY")
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
            raise ValueError("OpenAI embedding model requires CLOOP_OPENAI_API_KEY")
        kwargs["api_key"] = settings.openai_api_key

    return kwargs
