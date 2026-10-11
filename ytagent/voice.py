"""Step 3: text-to-speech, one audio file per script segment.

Synthesizing per segment gives exact segment durations, so visuals and captions
line up without needing word timestamps.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import requests

from .config import Settings
from .ffmpeg import probe_duration

log = logging.getLogger(__name__)

NARRATOR_INSTRUCTIONS = (
    "Calm, warm documentary narrator. Unhurried but engaging, clear diction, "
    "subtle emphasis on key words, natural pauses between sentences."
)


class TTSError(RuntimeError):
    pass


def _post_with_retry(url: str, *, headers: dict, json: dict, attempts: int = 4) -> bytes:
    for attempt in range(1, attempts + 1):
        try:
            r = requests.post(url, headers=headers, json=json, timeout=120)
            if r.status_code == 200:
                return r.content
            if r.status_code in (429, 500, 502, 503, 504) and attempt < attempts:
                time.sleep(2 ** attempt)
                continue
            raise TTSError(f"TTS-fel {r.status_code}: {r.text[:300]}")
        except requests.RequestException as e:
            if attempt == attempts:
                raise TTSError(f"TTS-nätverksfel: {e}") from e
            time.sleep(2 ** attempt)
    raise TTSError("TTS misslyckades")


def _openai(settings: Settings, text: str) -> bytes:
    if not settings.openai_api_key:
        raise TTSError("OPENAI_API_KEY saknas i .env")
    return _post_with_retry(
        "https://api.openai.com/v1/audio/speech",
        headers={"Authorization": f"Bearer {settings.openai_api_key}"},
        json={
            "model": settings.openai_tts_model,
            "voice": settings.openai_tts_voice,
            "input": text,
            "instructions": NARRATOR_INSTRUCTIONS,
            "response_format": "mp3",
        },
    )


def _elevenlabs(settings: Settings, text: str) -> bytes:
    if not (settings.elevenlabs_api_key and settings.elevenlabs_voice_id):
        raise TTSError("ELEVENLABS_API_KEY eller ELEVENLABS_VOICE_ID saknas i .env")
    return _post_with_retry(
        f"https://api.elevenlabs.io/v1/text-to-speech/{settings.elevenlabs_voice_id}?output_format=mp3_44100_128",
        headers={"xi-api-key": settings.elevenlabs_api_key},
        json={
            "text": text,
            "model_id": settings.elevenlabs_model,
            "voice_settings": {"stability": 0.6, "similarity_boost": 0.8, "style": 0.15},
        },
    )


PROVIDERS = {"openai": _openai, "elevenlabs": _elevenlabs}


def synthesize_segments(settings: Settings, texts: list[str], out_dir: Path) -> list[tuple[Path, float]]:
    provider = PROVIDERS.get(settings.tts_provider)
    if provider is None:
        raise TTSError(f"Okänd TTS_PROVIDER '{settings.tts_provider}'. Välj: {', '.join(PROVIDERS)}")
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for i, text in enumerate(texts):
        path = out_dir / f"voice_{i:02d}.mp3"
        if not path.exists():
            path.write_bytes(provider(settings, text))
        results.append((path, probe_duration(path)))
        log.info("Röst segment %d: %.1fs", i, results[-1][1])
    return results
