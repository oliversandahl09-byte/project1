"""Ordtider från YouTube-undertexter (VTT) eller, som reserv, OpenAI Whisper."""
from __future__ import annotations

import logging
import re
from pathlib import Path

import requests

from ytagent import ffmpeg

from .models import Word

log = logging.getLogger(__name__)

_TS = r"(\d+):(\d{2}):(\d{2})\.(\d{3})"
_CUE = re.compile(_TS + r"\s+-->\s+" + _TS)
_INLINE = re.compile(r"<" + _TS + r">")
_TAG = re.compile(r"</?[^>]+>")


def _secs(h, m, s, ms) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def parse_vtt(text: str) -> list[Word]:
    """Words with start/end times.

    YouTube's automatic captions carry per-word times as inline <00:00:01.234> tags,
    and repeat the previous line in every cue; manual captions have only cue times.
    """
    cues: list[tuple[float, float, list[str]]] = []
    for block in re.split(r"\n\s*\n", text.replace("\r", "")):
        lines = block.strip().split("\n")
        for i, line in enumerate(lines):
            m = _CUE.search(line)
            if m:
                cues.append((_secs(*m.groups()[:4]), _secs(*m.groups()[4:]), lines[i + 1:]))
                break

    has_inline = any(_INLINE.search(l) for _, _, ls in cues for l in ls)
    words: list[Word] = []
    last_line = ""
    for start, end, lines in cues:
        if has_inline:
            for line in lines:
                if not _INLINE.search(line):
                    continue  # the repeated previous line
                times = [start] + [_secs(*g) for g in _INLINE.findall(line)]
                parts = _INLINE.split(line)
                chunks = parts[::5]  # split() yields text, then the tag's 4 captured groups
                for t, chunk in zip(times, chunks):
                    for w in _TAG.sub("", chunk).split():
                        words.append(Word(start=t, end=end, text=w))
        else:
            line = " ".join(_TAG.sub("", l).strip() for l in lines).strip()
            if not line or line == last_line:
                continue
            last_line = line
            ws = line.split()
            total = sum(len(w) + 1 for w in ws)
            t = start
            for w in ws:
                dt = (end - start) * (len(w) + 1) / total
                words.append(Word(start=t, end=t + dt, text=w))
                t += dt
    words.sort(key=lambda w: w.start)
    for a, b in zip(words, words[1:]):
        a.end = min(max(a.start + 0.05, b.start), a.start + 1.5)
    if words:
        words[-1].end = min(words[-1].end, words[-1].start + 1.5)
    return words


def whisper(video: Path, work: Path, api_key: str) -> list[Word]:
    """Transcribe with OpenAI Whisper. Audio is compressed to stay under the 25 MB limit."""
    audio = work / "audio.mp3"
    ffmpeg.run(["-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "32k", str(audio)])
    if audio.stat().st_size > 25 * 1024 * 1024:
        raise RuntimeError("Videon är för lång för Whisper (över ca 1,5 timme)")
    with audio.open("rb") as f:
        r = requests.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_key}"},
            data={"model": "whisper-1", "response_format": "verbose_json", "timestamp_granularities[]": "word"},
            files={"file": ("audio.mp3", f, "audio/mpeg")},
            timeout=600,
        )
    if r.status_code != 200:
        raise RuntimeError(f"Whisper-fel {r.status_code}: {r.text[:300]}")
    return [Word(start=w["start"], end=w["end"], text=w["word"].strip()) for w in r.json().get("words", [])]


def as_lines(words: list[Word], seconds: float = 8.0) -> str:
    """Transcript as '[mm:ss] text' lines for Claude."""
    out, cur, cur_start = [], [], None
    for w in words:
        if cur_start is None:
            cur_start = w.start
        cur.append(w.text)
        if w.end - cur_start >= seconds or w.text.endswith((".", "?", "!")) and w.end - cur_start >= 3:
            out.append(f"[{_mmss(cur_start)}] {' '.join(cur)}")
            cur, cur_start = [], None
    if cur:
        out.append(f"[{_mmss(cur_start)}] {' '.join(cur)}")
    return "\n".join(out)


def _mmss(t: float) -> str:
    t = int(t)
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60:02d}:{t % 60:02d}"
