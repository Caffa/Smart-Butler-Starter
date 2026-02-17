"""Structured LLM calls via instructor (Pydantic) and tenacity retries."""

from typing import TypeVar, Type

import instructor
import requests
from pydantic import BaseModel
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from .types import OLLAMA_READ_TIMEOUT
from .memory import (
    acquire_ollama_lock,
    release_ollama_lock,
    log_debug,
)

T = TypeVar("T", bound=BaseModel)


def _log_retry(retry_state):
    """Tenacity callback: log each retry attempt."""
    if retry_state.outcome and retry_state.outcome.failed:
        exc = retry_state.outcome.exception()
        log_debug(
            f"⚠️ Retry attempt {retry_state.attempt_number} after {type(exc).__name__}: {exc}"
        )


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    retry=retry_if_exception_type(
        (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
            TimeoutError,
        )
    ),
    reraise=True,
    after=_log_retry,
)
def call_llm_structured(
    system: str,
    user: str,
    model: str,
    response_model: Type[T],
    max_retries: int = 2,
    timeout: float = None,
) -> T:
    """
    Call LLM with structured output via instructor.

    Validates the JSON against the Pydantic schema and auto-retries with
    error feedback to the LLM if validation fails (instructor's max_retries).
    Tenacity retries on network timeouts/connection errors.

    Args:
        system: System prompt
        user: User prompt
        model: Ollama model name (e.g. gemma3:12b)
        response_model: Pydantic model class for response
        max_retries: How many times instructor should retry on validation errors
        timeout: Total timeout in seconds (default: OLLAMA_READ_TIMEOUT)

    Returns:
        Validated Pydantic model instance

    Raises:
        Retries automatically on network errors (tenacity).
        Raises ValidationError if LLM cannot produce valid output after retries.
    """
    if timeout is None:
        timeout = float(OLLAMA_READ_TIMEOUT)

    lock_fd, locked = acquire_ollama_lock()
    try:
        client = instructor.from_provider(
            f"ollama/{model}",
            mode=instructor.Mode.JSON,
        )
        response = client.create(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_model=response_model,
            max_retries=max_retries,
            timeout=timeout,
        )
        return response
    finally:
        if locked:
            release_ollama_lock(lock_fd)
