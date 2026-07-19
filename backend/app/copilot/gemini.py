"""Thin async wrapper around the google-genai SDK."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from ..config import Settings
from .prompts import OUTLOOK_VISION_PROMPT, CopilotReply, OutlookExtract

logger = logging.getLogger("navier.copilot.gemini")


@dataclass
class GeminiResult:
    """Outcome of one generate call - exactly one of `reply` / `error` is set."""

    reply: CopilotReply | None = None
    error: str | None = None
    retry_after_s: float | None = None
    tokens: int | None = None

    @property
    def ok(self) -> bool:
        return self.reply is not None


_RETRY_RE = re.compile(r"retryDelay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)s")


def _retry_after(msg: str) -> float | None:
    m = _RETRY_RE.search(msg)
    return float(m.group(1)) if m else None


class GeminiClient:
    """Holds the SDK client. Constructing it imports the SDK (needs the `copilot` extra)."""

    def __init__(self, settings: Settings) -> None:
        from google import genai
        from google.genai import types

        self._s = settings
        self._types = types
        self._errors = __import__("google.genai.errors", fromlist=["errors"])
        self._client = genai.Client(
            api_key=settings.gemini_api_key,
            http_options=types.HttpOptions(timeout=int(settings.copilot_timeout_s * 1000)),
        )

    async def generate(self, model: str, contents: str) -> GeminiResult:
        """One structured co-pilot turn. Never raises - returns a typed result."""
        types = self._types
        try:
            resp = await self._client.aio.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=self._system_prompt(),
                    response_mime_type="application/json",
                    response_schema=CopilotReply,
                    temperature=self._s.copilot_temperature,
                    max_output_tokens=self._s.copilot_max_tokens,
                ),
            )
        except self._errors.APIError as e:
            code = getattr(e, "code", None)
            msg = str(getattr(e, "message", "") or e)
            if code == 429:
                return GeminiResult(error="quota", retry_after_s=_retry_after(msg))
            logger.warning("gemini API error %s: %s", code, msg[:200])
            return GeminiResult(error="unavailable")
        except Exception as e:  # noqa: BLE001
            logger.warning("gemini call failed: %s", e)
            return GeminiResult(error="unavailable")

        tokens = getattr(getattr(resp, "usage_metadata", None), "total_token_count", None)
        reply = resp.parsed if isinstance(resp.parsed, CopilotReply) else self._reparse(resp)
        if reply is None:
            return GeminiResult(error="empty", tokens=tokens)
        if reply.speak and not reply.tts_text.strip():
            reply.tts_text = reply.reply[:200]
        return GeminiResult(reply=reply, tokens=tokens)

    async def extract_outlook(
        self, image_bytes: bytes, mime_type: str = "image/png"
    ) -> OutlookExtract | None:
        """Read the PRETEMP map image into a structured level/zones. None on failure."""
        types = self._types
        try:
            resp = await self._client.aio.models.generate_content(
                model=self._s.gemini_model_chat,
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                    OUTLOOK_VISION_PROMPT,
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=OutlookExtract,
                    temperature=0.0,
                    max_output_tokens=self._s.copilot_max_tokens,
                ),
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("gemini outlook vision failed: %s", e)
            return None
        parsed = resp.parsed
        if isinstance(parsed, OutlookExtract):
            return parsed
        text = getattr(resp, "text", None)
        if not text:
            return None
        try:
            return OutlookExtract.model_validate_json(text)
        except ValueError:
            return None

    def _reparse(self, resp) -> CopilotReply | None:
        text = getattr(resp, "text", None)
        if not text:
            return None
        try:
            return CopilotReply.model_validate_json(text)
        except ValueError:
            return None

    def _system_prompt(self) -> str:
        from .prompts import SYSTEM_PROMPT

        return SYSTEM_PROMPT
