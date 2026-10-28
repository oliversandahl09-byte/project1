"""Hittar höjdpunkter: Claude läser transkriptet, annars ljudnivån som reserv."""
from __future__ import annotations

import logging
import math
import subprocess
from array import array
from pathlib import Path

from ytagent.config import Settings

from .models import Highlight, HighlightList, Word
from .transcript import as_lines

log = logging.getLogger(__name__)

SYSTEM = """Du är en erfaren TikTok-redigerare. Du hittar de ögonblick i en lång video som fungerar
som egna korta klipp: starka påståenden, roliga eller överraskande stunder, tydliga tips, känslor,
konflikter, punchlines. Varje klipp måste gå att förstå utan resten av videon och börja med en
krok som fångar tittaren inom 1-2 sekunder. Klippen får inte överlappa."""


def find(video: Path, words: list[Word], duration: float, title: str, settings: Settings,
         count: int = 6, min_len: float = 15, max_len: float = 60) -> tuple[list[Highlight], str]:
    """Returns (highlights, method)."""
    if words and settings.anthropic_api_key:
        try:
            return with_claude(words, duration, title, settings, count, min_len, max_len), "claude"
        except Exception as e:
            log.warning("Claude kunde inte välja höjdpunkter (%s), använder ljudnivå", e)
    length = int(min(max(30, min_len), max_len))
    return by_audio(video, words, count, length), "audio"


def with_claude(words: list[Word], duration: float, title: str, settings: Settings,
                count: int, min_len: float, max_len: float) -> list[Highlight]:
    from ytagent.llm import Claude

    prompt = f"""Videons titel: {title}
Längd: {duration:.0f} sekunder

Transkript med tidsstämplar [mm:ss]:
{as_lines(words)}

Välj upp till {count} höjdpunkter, bäst först. Varje klipp ska vara {min_len:.0f}-{max_len:.0f} sekunder.
Ange start och slut i sekunder. Starta på början av en mening och sluta efter en avslutad tanke.
Skriv title och caption på samma språk som videon."""
    result = Claude(settings).structured(SYSTEM, prompt, HighlightList)
    return clean(result.highlights, words, duration, min_len, max_len)


def clean(highlights: list[Highlight], words: list[Word], duration: float,
          min_len: float, max_len: float) -> list[Highlight]:
    """Clamp to the video, snap to word boundaries and drop overlaps."""
    out: list[Highlight] = []
    for h in sorted(highlights, key=lambda h: -h.score):
        start, end = max(0.0, h.start), min(duration or h.end, h.end)
        if words:
            before = [w.start for w in words if w.start <= start + 0.3]
            start = before[-1] if before else start
            after = [w.end for w in words if w.end >= end - 0.3]
            end = min(after[0] + 0.3, duration or after[0] + 0.3) if after else end
        end = min(end, start + max_len)
        if end - start < min(min_len, 5):
            continue
        if any(start < o.end and end > o.start for o in out):
            continue
        out.append(h.model_copy(update={"start": round(start, 2), "end": round(end, 2)}))
    return out


def loudness(video: Path, rate: int = 1000) -> list[float]:
    """RMS level per second of audio."""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(video), "-vn", "-ac", "1",
         "-ar", str(rate), "-f", "s16le", "-"],
        capture_output=True,
    )
    samples = array("h", proc.stdout[: len(proc.stdout) // 2 * 2])
    levels = []
    for i in range(0, len(samples), rate):
        chunk = samples[i:i + rate]
        levels.append(math.sqrt(sum(x * x for x in chunk) / max(len(chunk), 1)))
    return levels


def by_audio(video: Path, words: list[Word], count: int = 6, length: int = 30) -> list[Highlight]:
    """Fallback: the loudest, liveliest windows (laughter, raised voices, music drops)."""
    levels = loudness(video)
    if not levels:
        return []
    length = min(length, len(levels))
    mean = sum(levels) / len(levels) or 1.0
    density = [0.0] * len(levels)
    for w in words:
        if int(w.start) < len(density):
            density[int(w.start)] += 1

    def score(s: int) -> float:
        win = levels[s:s + length]
        avg = sum(win) / len(win)
        peak = max(win)
        talk = sum(density[s:s + length]) / length
        return avg / mean + 0.5 * peak / (max(levels) or 1) + 0.1 * talk

    candidates = sorted(range(0, len(levels) - length + 1, 2), key=score, reverse=True)
    picked: list[int] = []
    for s in candidates:
        if all(abs(s - p) >= length for p in picked):
            picked.append(s)
        if len(picked) == count:
            break
    best = score(picked[0]) if picked else 1
    out = []
    for n, s in enumerate(picked, 1):
        out.append(Highlight(
            start=float(s), end=float(s + length), title=f"Höjdpunkt {n}",
            reason="Hög och livlig ljudnivå (vald utan AI)",
            score=max(1, min(10, round(10 * score(s) / best))), caption="",
        ))
    return out
