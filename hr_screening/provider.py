"""Narrow OpenRouter client with the approved retry policy.

Each call sends only the approved listing, scoring guidance, one candidate's
CV text, and the task. The API key is used by the client and never included in
prompts, errors, logs, or output.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Callable

from openai import APITimeoutError, InternalServerError, OpenAI, RateLimitError

from .config import Settings
from .errors import ProviderRequestError, ResponseParseError

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_REQUEST_TIMEOUT_SECONDS = 120.0
_RETRY_DELAY_SECONDS = 2.0
_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.IGNORECASE | re.DOTALL)


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, APITimeoutError):
        return True
    if isinstance(exc, (RateLimitError, InternalServerError)):
        return True
    status = getattr(exc, "status_code", None)
    if status == 429:
        return True
    if isinstance(status, int) and 500 <= status < 600:
        return True
    return False


def _safe_provider_error(
    exc: Exception, candidate_label: str, retried: bool
) -> ProviderRequestError:
    status = getattr(exc, "status_code", None)
    kind = type(exc).__name__
    retry_note = " after one retry" if retried else ""
    if isinstance(exc, APITimeoutError):
        return ProviderRequestError(
            f"Provider request timed out for {candidate_label} after "
            f"{int(_REQUEST_TIMEOUT_SECONDS)} seconds{retry_note}. "
            "The run was stopped; no bundle was written."
        )
    if status == 429:
        return ProviderRequestError(
            f"Provider rate limit (HTTP 429) for {candidate_label}{retry_note}. "
            "The run was stopped; no bundle was written."
        )
    if isinstance(status, int) and 500 <= status < 600:
        return ProviderRequestError(
            f"Provider server error (HTTP {status}) for {candidate_label}{retry_note}. "
            "The run was stopped; no bundle was written."
        )
    if status is not None:
        return ProviderRequestError(
            f"Provider request failed for {candidate_label} "
            f"(HTTP {status}, {kind}){retry_note}. "
            "The run was stopped; no bundle was written."
        )
    return ProviderRequestError(
        f"Provider request failed for {candidate_label} ({kind}){retry_note}. "
        "The run was stopped; no bundle was written."
    )


def _extract_content(response: Any) -> str:
    try:
        choices = response.choices
        if not choices:
            raise ResponseParseError("The provider returned no response choices.")
        message = choices[0].message
        content = message.content
    except ResponseParseError:
        raise
    except Exception as exc:
        raise ResponseParseError(
            "The provider response did not contain readable message content."
        ) from exc

    if isinstance(content, str) and content.strip():
        return content

    # Reasoning models (e.g. DeepSeek V4 Flash) can return content=None
    # when the output is entirely in the reasoning field. Fall back to it.
    extra = getattr(message, "model_extra", None) or {}
    reasoning = extra.get("reasoning") or extra.get("reasoning_content")
    if isinstance(reasoning, str) and reasoning.strip():
        return reasoning

    raise ResponseParseError("The provider returned an empty message.")


def parse_json_object(content: str) -> dict:
    """Parse one JSON object, tolerating only a surrounding Markdown fence."""

    text = content.strip()
    fence = _FENCE_RE.match(text)
    if fence:
        text = fence.group(1).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ResponseParseError(
            "The model response was not valid JSON. The run was stopped; "
            "no bundle was written."
        ) from exc
    if not isinstance(parsed, dict):
        raise ResponseParseError(
            "The model response was not a single JSON object. The run was stopped; "
            "no bundle was written."
        )
    return parsed


class OpenRouterProvider:
    """One request per candidate, with one retry only for timeout/429/5xx."""

    def __init__(
        self,
        settings: Settings,
        client: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._settings = settings
        self._sleep = sleep
        self._client = client or OpenAI(
            api_key=settings.api_key,
            base_url=_OPENROUTER_BASE_URL,
            max_retries=0,
        )

    @property
    def model_handle(self) -> str:
        return self._settings.model

    def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        candidate_label: str,
    ) -> dict:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        retried = False
        while True:
            try:
                response = self._client.chat.completions.create(
                    model=self._settings.model,
                    messages=messages,
                    timeout=_REQUEST_TIMEOUT_SECONDS,
                )
                break
            except Exception as exc:
                if not retried and _is_retryable(exc):
                    retried = True
                    self._sleep(_RETRY_DELAY_SECONDS)
                    continue
                raise _safe_provider_error(exc, candidate_label, retried) from None

        content = _extract_content(response)
        return parse_json_object(content)
