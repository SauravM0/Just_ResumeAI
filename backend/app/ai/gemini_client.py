"""
Gemini API client — wrapper for structured JSON generation with retry logic.

Design:
- Every call requests JSON-mode output from Gemini.
- The expected JSON schema is embedded in the prompt (not via response_schema,
  which doesn't support Pydantic defaults).
- Responses are validated against a Pydantic model.
- On transient failure (timeout, 429, 5xx), retries with exponential backoff + jitter.
- On validation failure, retries with a repair prompt.
- After exhausting retries, raises GeminiClientError with a safe message.
- Never logs raw AI output (contains user resume data).
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import TypeVar, Type

from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError

from app.config import get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def _schema_to_prompt_description(model: Type[BaseModel]) -> str:
    schema = model.model_json_schema()

    def _clean(d: dict) -> dict:
        d.pop("title", None)
        d.pop("description", None)
        if "properties" in d:
            for prop_val in d["properties"].values():
                if isinstance(prop_val, dict):
                    _clean(prop_val)
        if "$defs" in d:
            for def_val in d["$defs"].values():
                if isinstance(def_val, dict):
                    _clean(def_val)
        if "items" in d and isinstance(d["items"], dict):
            _clean(d["items"])
        return d

    cleaned = _clean(schema)
    return json.dumps(cleaned, indent=2)


class GeminiClientError(Exception):
    """Raised when Gemini call fails after retries."""

    def __init__(self, message: str):
        super().__init__(message)


class GeminiClient:
    """
    Wrapper around the Gemini GenAI SDK.
    Enforces structured JSON output + Pydantic validation + retry.
    Reads all config from environment at construction time.
    """

    def __init__(self):
        settings = get_settings()
        if not settings.GEMINI_API_KEY:
            raise GeminiClientError(
                "Gemini API key is not configured. "
                "Set GEMINI_API_KEY in your environment or .env file."
            )
        self._client = genai.Client(api_key=settings.GEMINI_API_KEY)
        self._model = settings.GEMINI_MODEL
        self._max_retries = settings.GEMINI_MAX_RETRIES
        self._temperature = settings.GEMINI_TEMPERATURE
        self._timeout = settings.GEMINI_TIMEOUT_SECONDS
        self._retry_base_delay = settings.GEMINI_RETRY_BASE_DELAY_SECONDS
        self._retry_max_delay = settings.GEMINI_RETRY_MAX_DELAY_SECONDS

    async def generate_structured(
        self,
        prompt: str,
        response_model: Type[T],
        system_instruction: str | None = None,
        temperature: float | None = None,
    ) -> T:
        """
        Send a prompt to Gemini and parse the response into a Pydantic model.

        Args:
            prompt: The user/task prompt.
            response_model: Pydantic model class to validate the JSON output against.
            system_instruction: Optional system-level instruction.
            temperature: Override default temperature for this call.

        Returns:
            Validated Pydantic model instance.

        Raises:
            GeminiClientError: If generation or validation fails after retries.
        """
        temp = temperature if temperature is not None else self._temperature

        schema_text = _schema_to_prompt_description(response_model)
        schema_instruction = (
            f"\n\nYou MUST respond with ONLY valid JSON matching this exact schema:\n"
            f"```json\n{schema_text}\n```\n"
            f"Do not include any text outside the JSON object."
        )

        augmented_prompt = prompt + schema_instruction

        config = types.GenerateContentConfig(
            temperature=temp,
            response_mime_type="application/json",
        )
        if system_instruction:
            config.system_instruction = system_instruction

        raw_text: str | None = None
        error_msg: str = ""

        total_attempts = 1 + self._max_retries
        for attempt in range(total_attempts):
            try:
                logger.info(
                    "Calling Gemini model=%s attempt=%s/%s model=%s",
                    self._model,
                    attempt + 1,
                    total_attempts,
                    response_model.__name__,
                )
                response = await asyncio.wait_for(
                    self._client.aio.models.generate_content(
                        model=self._model,
                        contents=augmented_prompt if attempt == 0 else self._build_repair_prompt(augmented_prompt, raw_text, error_msg),
                        config=config,
                    ),
                    timeout=self._timeout,
                )
                raw_text = response.text
                if not raw_text:
                    raise GeminiClientError("Gemini returned an empty response. Please retry.")

                parsed = _parse_json_object(raw_text)
                return response_model.model_validate(parsed)

            except (json.JSONDecodeError, ValidationError) as e:
                error_msg = str(e)
                response_len = len(raw_text or "")
                logger.warning(
                    "Gemini response validation failed model=%s attempt=%s/%s error=%s response_len=%s",
                    self._model,
                    attempt + 1,
                    total_attempts,
                    error_msg,
                    response_len,
                )
                if attempt >= self._max_retries:
                    raise GeminiClientError(
                        f"AI response could not be processed after {1 + self._max_retries} attempts. "
                        f"Please retry."
                    )
                await asyncio.sleep(self._backoff_delay(attempt))

            except asyncio.TimeoutError:
                error_msg = f"Gemini call timed out after {self._timeout} seconds"
                logger.warning(
                    "Gemini timeout model=%s attempt=%s/%s timeout=%ss",
                    self._model,
                    attempt + 1,
                    total_attempts,
                    self._timeout,
                )
                if attempt >= self._max_retries:
                    raise GeminiClientError(
                        f"AI service did not respond in time after {1 + self._max_retries} attempts. "
                        f"Please retry."
                    )
                await asyncio.sleep(self._backoff_delay(attempt))

            except GeminiClientError:
                raise

            except Exception as e:
                if self._is_transient_error(e) and attempt < self._max_retries:
                    is_quota = "429" in str(e).upper() or "RESOURCE_EXHAUSTED" in str(e).upper()
                    logger.warning(
                        "Transient Gemini API error attempt=%s/%s is_quota=%s",
                        attempt + 1,
                        total_attempts,
                        is_quota,
                    )
                    await asyncio.sleep(self._backoff_delay(attempt, is_quota))
                    continue

                logger.error(
                    "Gemini API error model=%s attempt=%s/%s",
                    self._model,
                    attempt + 1,
                    total_attempts,
                )
                raise GeminiClientError(
                    "AI service is temporarily unavailable. Please retry later."
                )

        raise GeminiClientError(
            "AI service is temporarily unavailable after exhausting retries. Please retry later."
        )

    def _build_repair_prompt(self, original_prompt: str, bad_response: str | None, error: str) -> str:
        return (
            f"Your previous response was invalid JSON or failed schema validation.\n"
            f"Error: {error}\n\n"
            f"Previous response (truncated):\n{(bad_response or '')[:2000]}\n\n"
            f"Please fix the response to match the required schema exactly.\n\n"
            f"Original task:\n{original_prompt}"
        )

    def _backoff_delay(self, attempt: int, is_quota: bool = False) -> float:
        base = self._retry_base_delay
        if is_quota:
            base = max(base, 5.0)
        delay = min(base * (2 ** attempt), self._retry_max_delay)
        delay += random.uniform(0, 1.0)
        return delay

    def _is_transient_error(self, error: Exception) -> bool:
        message = str(error).upper()
        transient_markers = (
            "429",
            "500",
            "502",
            "503",
            "504",
            "DEADLINE_EXCEEDED",
            "INTERNAL",
            "RESOURCE_EXHAUSTED",
            "SERVICE UNAVAILABLE",
            "TOO MANY REQUESTS",
            "UNAVAILABLE",
        )
        return any(marker in message for marker in transient_markers)


def _parse_json_object(raw_text: str) -> dict:
    """Parse JSON mode output, tolerating fenced JSON or stray wrapper text."""
    try:
        parsed = json.loads(raw_text)
        if isinstance(parsed, dict):
            return parsed
        raise json.JSONDecodeError("Top-level JSON is not an object", raw_text, 0)
    except json.JSONDecodeError:
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            cleaned = cleaned.removeprefix("json").strip()
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        parsed = json.loads(cleaned[start : end + 1])
        if not isinstance(parsed, dict):
            raise json.JSONDecodeError("Top-level JSON is not an object", cleaned, 0)
        return parsed


_client: GeminiClient | None = None


def get_gemini_client() -> GeminiClient:
    """Get or create the singleton Gemini client."""
    global _client
    if _client is None:
        _client = GeminiClient()
    return _client


def reset_gemini_client() -> None:
    """Reset the singleton (for testing or config changes)."""
    global _client
    _client = None
