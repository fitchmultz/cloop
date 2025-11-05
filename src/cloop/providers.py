from typing import Any, Dict

from .settings import Settings


def resolve_provider_kwargs(model: str, settings: Settings) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {}
    model_lower = model.lower()

    if model_lower.startswith("ollama/") and not settings.ollama_api_base:
        raise ValueError("ollama/... requires CLOOP_OLLAMA_API_BASE")

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
