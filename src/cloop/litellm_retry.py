"""Shared retry logic for embeddings-only LiteLLM calls.

Purpose:
    Provide a tenacity-based retry wrapper for transient embedding failures.

Responsibilities:
    - Centralize retryable LiteLLM embedding exception handling
    - Apply settings-driven retry/backoff behavior
    - Emit consistent warning logs before retry attempts

Non-scope:
    - Generative pi bridge retries
    - Embedding provider credential resolution
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

RETRIABLE_EXCEPTIONS = (
    litellm.Timeout,
    litellm.RateLimitError,
    litellm.APIConnectionError,
    litellm.ServiceUnavailableError,
)


def _log_retry_attempt(retry_state: RetryCallState) -> None:
    if retry_state.outcome is None:
        return

    exception = retry_state.outcome.exception()
    if exception is None:
        return

    logger.warning(
        "LiteLLM embedding call failed (attempt %d), retrying: %s",
        retry_state.attempt_number,
        type(exception).__name__,
    )


def with_litellm_retry(func, settings: Settings | None = None):
    settings = settings or get_settings()

    @retry(
        retry=retry_if_exception_type(RETRIABLE_EXCEPTIONS),
        stop=stop_after_attempt(settings.llm_max_retries + 1),
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
