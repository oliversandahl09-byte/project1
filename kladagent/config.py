"""Settings loaded from .env. API keys live only in .env, never in code."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    anthropic_api_key: str = ""
    claude_model: str = "claude-opus-5-5"
    effort: str = "medium"
    vinted_domain: str = "vinted.se"
    currency: str = "SEK"
    host: str = "127.0.0.1"
    port: int = 5000


def load_settings() -> Settings:
    load_dotenv(ROOT / ".env")
    s = Settings()
    s.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "")
    s.claude_model = os.getenv("CLAUDE_MODEL") or s.claude_model
    s.effort = os.getenv("KLAD_EFFORT") or s.effort
    s.vinted_domain = os.getenv("KLAD_VINTED_DOMAIN") or s.vinted_domain
    s.currency = os.getenv("KLAD_CURRENCY") or s.currency
    s.host = os.getenv("KLAD_HOST") or s.host
    s.port = int(os.getenv("KLAD_PORT") or s.port)
    return s
