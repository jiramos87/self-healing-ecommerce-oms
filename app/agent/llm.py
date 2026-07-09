"""OpenRouter primary + Groq fallback LLM client with call caps."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
GROQ_BASE = "https://api.groq.com/openai/v1"

CLASSIFY_MODEL = "google/gemini-3.1-flash-lite"
DIAGNOSE_MODEL = "google/gemini-3.5-flash"
FALLBACK_MODEL = "llama-3.3-70b-versatile"

MAX_LLM_CALLS = 3
MAX_TOKENS = 512


class LlmError(RuntimeError):
    """Both providers failed or the call budget was exhausted."""


@dataclass
class LlmCallResult:
    text: str
    served_by: str
    model: str
    ms: int


@dataclass
class LlmClient:
    """OpenAI-compatible chat completions with OpenRouter then Groq."""

    openrouter_api_key: str | None = None
    groq_api_key: str | None = None
    openrouter_base_url: str | None = None
    call_count: int = 0
    max_calls: int = MAX_LLM_CALLS
    _transport: Any = field(default=None, repr=False)
    _http: Any = field(default=None, repr=False)

    @classmethod
    def from_env(cls) -> LlmClient:
        return cls(
            openrouter_api_key=os.environ.get("OPENROUTER_API_KEY"),
            groq_api_key=os.environ.get("GROQ_API_KEY"),
            openrouter_base_url=os.environ.get("OPENROUTER_BASE_URL") or OPENROUTER_BASE,
        )

    def _http_client(self) -> httpx.Client:
        # One client per LlmClient so sequential calls reuse the TLS session.
        if self._http is None:
            self._http = httpx.Client(timeout=60.0)
        return self._http

    def chat(
        self,
        *,
        messages: list[dict[str, str]],
        model: str,
        temperature: float = 0.0,
        max_tokens: int = MAX_TOKENS,
    ) -> LlmCallResult:
        if self.call_count >= self.max_calls:
            raise LlmError("llm_call_cap")

        self.call_count += 1
        primary_error: Exception | None = None
        try:
            return self._request(
                base_url=self.openrouter_base_url or OPENROUTER_BASE,
                api_key=self.openrouter_api_key,
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                served_by=model,
            )
        except Exception as exc:  # noqa: BLE001
            primary_error = exc  # fall through to the Groq fallback

        try:
            return self._request(
                base_url=GROQ_BASE,
                api_key=self.groq_api_key,
                model=FALLBACK_MODEL,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                served_by="fallback",
            )
        except Exception as exc:  # noqa: BLE001
            raise LlmError(
                f"providers_down primary={primary_error} fallback={exc}"
            ) from exc

    def _request(
        self,
        *,
        base_url: str,
        api_key: str | None,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        served_by: str,
    ) -> LlmCallResult:
        if not api_key:
            raise LlmError(f"missing_api_key for {base_url}")
        started = time.perf_counter()
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if self._transport is not None:
            # Test double: callable(payload) -> text
            text = self._transport(payload, base_url=base_url, served_by=served_by)
            ms = int((time.perf_counter() - started) * 1000)
            return LlmCallResult(text=text, served_by=served_by, model=model, ms=ms)

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        response = self._http_client().post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        text = data["choices"][0]["message"]["content"]
        ms = int((time.perf_counter() - started) * 1000)
        return LlmCallResult(text=text or "", served_by=served_by, model=model, ms=ms)


def parse_json_object(text: str) -> dict[str, Any]:
    """Extract a JSON object from model output (raw or fenced)."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        lines = [ln for ln in lines if not ln.strip().startswith("```")]
        cleaned = "\n".join(lines).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("no_json_object")
    return json.loads(cleaned[start : end + 1])
