"""
Gemini API client — wrapper for structured JSON generation with retry logic.

Design:
- Every call requests JSON-mode output from Gemini.
- The expected JSON schema is embedded in the prompt (not via response_schema,
  which doesn't support Pydantic defaults).
- Responses are validated against a Pydantic model.
- On validation failure, a single retry with a repair prompt is attempted.
- On second failure, a structured error is returned instead of crashing.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TypeVar, Type

from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError

from app.config import get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def _schema_to_prompt_description(model: Type[BaseModel]) -> str:
    """
    Generate a compact JSON schema description from a Pydantic model
    to embed in the prompt. This avoids the Gemini API limitation
    where response_schema rejects models with default values.
    """
    schema = model.model_json_schema()

    # Strip internal Pydantic metadata that adds noise
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

    def __init__(self, message: str, raw_response: str | None = None):
        super().__init__(message)
        self.raw_response = raw_response


class GeminiClient:
    """
    Wrapper around the Gemini GenAI SDK.
    Enforces structured JSON output + Pydantic validation + retry.
    """

    def __init__(self):
        settings = get_settings()
        self._client = genai.Client(api_key=settings.GEMINI_API_KEY)
        self._model = settings.GEMINI_MODEL
        self._max_retries = settings.GEMINI_MAX_RETRIES
        self._temperature = settings.GEMINI_TEMPERATURE
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

        Strategy: We use response_mime_type="application/json" for JSON-mode,
        but embed the schema in the prompt instead of using response_schema
        (which rejects Pydantic models with default field values).

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

        # Embed schema in prompt instead of response_schema
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
                response = await self._client.aio.models.generate_content(
                    model=self._model,
                    contents=augmented_prompt if attempt == 0 else self._build_repair_prompt(augmented_prompt, raw_text, error_msg),
                    config=config,
                )
                raw_text = response.text
                if not raw_text:
                    raise GeminiClientError("Gemini returned empty response")

                # Parse and validate
                parsed = json.loads(raw_text)
                return response_model.model_validate(parsed)

            except (json.JSONDecodeError, ValidationError) as e:
                error_msg = str(e)
                logger.warning(
                    f"Gemini response validation failed (attempt {attempt + 1}): {error_msg}"
                )
                if attempt >= self._max_retries:
                    raise GeminiClientError(
                        f"Failed to get valid response after {1 + self._max_retries} attempts: {error_msg}",
                        raw_response=raw_text,
                    )
                await asyncio.sleep(self._backoff_delay(attempt))
            except GeminiClientError:
                raise
            except Exception as e:
                if self._is_transient_error(e) and attempt < self._max_retries:
                    logger.warning(
                        "Transient Gemini API error on attempt %s/%s: %s",
                        attempt + 1,
                        total_attempts,
                        e,
                    )
                    await asyncio.sleep(self._backoff_delay(attempt))
                    continue

                logger.error(f"Gemini API error: {e}")
                raise GeminiClientError(f"Gemini API call failed: {e}")

        # Shouldn't reach here, but safety net
        raise GeminiClientError("Exhausted retries", raw_response=raw_text)

    def _build_repair_prompt(self, original_prompt: str, bad_response: str | None, error: str) -> str:
        """Build a repair prompt that includes the validation error for retry."""
        return (
            f"Your previous response was invalid JSON or failed schema validation.\n"
            f"Error: {error}\n\n"
            f"Previous response (truncated):\n{(bad_response or '')[:2000]}\n\n"
            f"Please fix the response to match the required schema exactly.\n\n"
            f"Original task:\n{original_prompt}"
        )

    def _backoff_delay(self, attempt: int) -> float:
        return min(self._retry_base_delay * (2 ** attempt), self._retry_max_delay)

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


# Module-level singleton
_client: GeminiClient | None = None


def get_gemini_client() -> GeminiClient:
    """Get or create the singleton Gemini client."""
    global _client
    if _client is None:
        _client = GeminiClient()
    return _client
