"""Shared retry logic for LLM and embedding API calls.

Purpose:
    Provide a tenacity-based retry decorator configured for transient
    LLM/embedding API failures with exponential backoff and logging.

Responsibilities:
    - Define which litellm exceptions are retriable vs permanent
    - Configure exponential backoff with jitter
    - Log retry attempts for observability

Non-scope:
    - Webhook retries (see webhooks/service.py for custom logic)
    - Database retries (different error types)

Entrypoints:
    - with_llm_retry(callable) -> wrapped callable with retry logic
"""

import logging
from typing import TypeVar

import litellm
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from .settings import Settings, get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T")

# litellm exceptions that are transient and should be retried
RETRIABLE_EXCEPTIONS = (
    litellm.Timeout,
    litellm.RateLimitError,
    litellm.APIConnectionError,
    litellm.ServiceUnavailableError,
)

# litellm exceptions that are permanent and should NOT be retried
# - litellm.AuthenticationError: Bad credentials won't fix themselves
# - litellm.ContextWindowExceededError: Prompt too large won't shrink
# - litellm.BadRequestError: Invalid request won't become valid


def _log_retry_attempt(retry_state: RetryCallState) -> None:
    """Log retry attempts for observability."""
    if retry_state.outcome is None:
        return

    exception = retry_state.outcome.exception()
    if exception is None:
        return

    logger.warning(
        "LLM API call failed (attempt %d), retrying: %s",
        retry_state.attempt_number,
        type(exception).__name__,
    )


def with_llm_retry(func, settings: Settings | None = None):
    """Wrap a function with LLM retry logic.

    Args:
        func: The function to wrap (typically litellm.completion or litellm.embedding)
        settings: Optional settings override

    Returns:
        Wrapped function with retry logic

    Usage:
        response = with_llm_retry(litellm.completion, settings)(
            model=model,
            messages=messages,
            **kwargs
        )
    """
    settings = settings or get_settings()

    @retry(
        retry=retry_if_exception_type(RETRIABLE_EXCEPTIONS),
        stop=stop_after_attempt(settings.llm_max_retries + 1),  # +1 for initial attempt
        wait=wait_exponential_jitter(
            initial=settings.llm_retry_min_wait,
            max=settings.llm_retry_max_wait,
            exp_base=2,
        ),
        before_sleep=_log_retry_attempt,
        reraise=True,
    )
    def _wrapped(*args, **kwargs):
        return func(*args, **kwargs)

    return _wrapped
