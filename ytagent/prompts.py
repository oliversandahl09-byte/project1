"""Shared context that every Claude call gets: brief, style guide, learnings."""
from __future__ import annotations

from pathlib import Path

POLICY = """\
YouTube rules you must follow:
- Every video must be original and add real value. No templated, repetitive or mass-produced content:
  vary topics, structure, hooks and examples. Never reuse a script.
- No misleading titles or thumbnails: the video must deliver what the title promises.
- No copyrighted material. Only licensed stock footage and our own text/voice.
- Facts must be accurate. If unsure, leave it out rather than invent.
"""


def read_optional(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def channel_context(brief_text: str, style_guide: str, learnings: str, history_titles: list[str]) -> str:
    parts = [f"<brief>\n{brief_text}\n</brief>"]
    if style_guide:
        parts.append(f"<style_guide>\n{style_guide}\n</style_guide>")
    if learnings:
        parts.append(f"<learnings_from_analytics>\n{learnings}\n</learnings_from_analytics>")
    if history_titles:
        listed = "\n".join(f"- {t}" for t in history_titles[-60:])
        parts.append(f"<already_published_or_made>\n{listed}\n</already_published_or_made>")
    return "\n\n".join(parts)


SYSTEM = (
    "You are the creative director and head writer of a YouTube Shorts channel. "
    "You have strong taste, and you care about retention, clarity and giving viewers real value.\n\n"
    + POLICY
)
