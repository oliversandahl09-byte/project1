"""Settings loaded from .env. API keys live only in .env, never in code."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "ja"}


@dataclass
class Settings:
    root: Path = ROOT
    anthropic_api_key: str = ""
    claude_model: str = "claude-opus-5-5"
    claude_effort: str = "high"

    tts_provider: str = "openai"  # openai | elevenlabs
    openai_api_key: str = ""
    openai_tts_model: str = "gpt-4o-mini-tts"
    openai_tts_voice: str = "onyx"
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""
    elevenlabs_model: str = "eleven_multilingual_v2"

    pexels_api_key: str = ""

    approval_required: bool = True
    ai_disclosure: bool = True
    font_path: str = ""

    google_client_secret: Path = field(default_factory=lambda: ROOT / "secrets" / "client_secret.json")
    google_token: Path = field(default_factory=lambda: ROOT / "secrets" / "token.json")

    @property
    def brief_path(self) -> Path:
        return self.root / "brief.md"

    @property
    def style_guide_path(self) -> Path:
        return self.root / "style_guide.md"

    @property
    def learnings_path(self) -> Path:
        return self.root / "learnings.md"

    @property
    def output_dir(self) -> Path:
        return self.root / "output"

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def history_path(self) -> Path:
        return self.data_dir / "history.json"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def music_dir(self) -> Path:
        return self.root / "assets" / "music"

    @property
    def fonts_dir(self) -> Path:
        return self.root / "assets" / "fonts"


def load_settings(root: Path | None = None) -> Settings:
    root = root or ROOT
    load_dotenv(root / ".env")
    env = os.environ.get
    s = Settings(root=root)
    s.anthropic_api_key = env("ANTHROPIC_API_KEY", "")
    s.claude_model = env("CLAUDE_MODEL") or s.claude_model
    s.claude_effort = env("CLAUDE_EFFORT") or s.claude_effort
    s.tts_provider = (env("TTS_PROVIDER") or s.tts_provider).lower()
    s.openai_api_key = env("OPENAI_API_KEY", "")
    s.openai_tts_model = env("OPENAI_TTS_MODEL") or s.openai_tts_model
    s.openai_tts_voice = env("OPENAI_TTS_VOICE") or s.openai_tts_voice
    s.elevenlabs_api_key = env("ELEVENLABS_API_KEY", "")
    s.elevenlabs_voice_id = env("ELEVENLABS_VOICE_ID", "")
    s.elevenlabs_model = env("ELEVENLABS_MODEL") or s.elevenlabs_model
    s.pexels_api_key = env("PEXELS_API_KEY", "")
    s.approval_required = _bool(env("APPROVAL_REQUIRED"), True)
    s.ai_disclosure = _bool(env("AI_DISCLOSURE"), True)
    s.font_path = env("FONT_PATH", "")
    if env("GOOGLE_CLIENT_SECRET_FILE"):
        s.google_client_secret = root / env("GOOGLE_CLIENT_SECRET_FILE")
    if env("GOOGLE_TOKEN_FILE"):
        s.google_token = root / env("GOOGLE_TOKEN_FILE")
    return s
