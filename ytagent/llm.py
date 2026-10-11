"""Thin wrapper around the Claude API with structured (Pydantic) output."""
from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import TypeVar

import anthropic
from pydantic import BaseModel

from .config import Settings

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    pass


class Claude:
    def __init__(self, settings: Settings):
        if not settings.anthropic_api_key:
            raise LLMError("ANTHROPIC_API_KEY saknas i .env")
        self.settings = settings
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key, max_retries=3)

    def structured(self, system: str, prompt: str, schema: type[T], images: list[Path] | None = None) -> T:
        content: list[dict] = []
        for img in images or []:
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg" if img.suffix.lower() in {".jpg", ".jpeg"} else "image/png",
                    "data": base64.b64encode(img.read_bytes()).decode(),
                },
            })
        content.append({"type": "text", "text": prompt})

        response = self.client.beta.messages.parse(
            model=self.settings.claude_model,
            max_tokens=16000,
            system=system,
            thinking={"type": "adaptive"},
            output_config={"effort": self.settings.claude_effort},
            # If a request is declined by safety classifiers, the API retries it on a fallback model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": content}],
            output_format=schema,
        )
        if response.stop_reason == "refusal":
            raise LLMError(f"Claude avböjde förfrågan: {response.stop_details}")
        if response.stop_reason == "max_tokens":
            raise LLMError("Claude-svaret blev avklippt (max_tokens)")
        if response.parsed_output is None:
            raise LLMError("Claude gav inget giltigt strukturerat svar")
        log.debug("Claude usage: %s", response.usage)
        return response.parsed_output

    def text(self, system: str, prompt: str) -> str:
        response = self.client.beta.messages.create(
            model=self.settings.claude_model,
            max_tokens=16000,
            system=system,
            thinking={"type": "adaptive"},
            output_config={"effort": self.settings.claude_effort},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": prompt}],
        )
        if response.stop_reason == "refusal":
            raise LLMError(f"Claude avböjde förfrågan: {response.stop_details}")
        return "".join(b.text for b in response.content if b.type == "text").strip()
