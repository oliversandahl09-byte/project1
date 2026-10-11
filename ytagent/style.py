"""Creates and maintains style_guide.md: the channel's own taste."""
from __future__ import annotations

import logging

from .config import Settings
from .llm import Claude
from .prompts import SYSTEM, read_optional

log = logging.getLogger(__name__)

STYLE_TEMPLATE_HINT = """\
Write style_guide.md in markdown with these sections:
# Style guide
## Identity (one paragraph: what this channel is and feels like)
## Voice & tone (narrator persona, vocabulary, sentence length, words to avoid)
## Pacing (words per second, cut frequency in seconds, how fast the hook lands)
## Hook patterns (5 varied patterns we use; never the same twice in a row)
## Structure (beats of a typical short, with rough seconds)
## Visual style (footage types, color mood, what to avoid)
## On-screen text & captions (casing, length, emphasis)
## Thumbnail & title style (patterns, max lengths, examples of the vibe)
## Call to action (2-3 rotating CTAs that fit the channel)
## Do / Don't
Keep it concrete and opinionated, under 500 words.
"""


def ensure_style_guide(settings: Settings, claude: Claude, brief_text: str) -> str:
    path = settings.style_guide_path
    if path.exists():
        return path.read_text(encoding="utf-8")
    log.info("Skapar style_guide.md från brief.md")
    guide = claude.text(SYSTEM, f"<brief>\n{brief_text}\n</brief>\n\n{STYLE_TEMPLATE_HINT}")
    path.write_text(guide + "\n", encoding="utf-8")
    return guide


def update_style_guide(settings: Settings, claude: Claude, brief_text: str) -> str:
    """Revise the guide using the latest learnings. Called after analytics runs."""
    current = read_optional(settings.style_guide_path)
    learnings = read_optional(settings.learnings_path)
    if not learnings:
        return current
    prompt = (
        f"<brief>\n{brief_text}\n</brief>\n\n<current_style_guide>\n{current}\n</current_style_guide>\n\n"
        f"<learnings>\n{learnings}\n</learnings>\n\n"
        "Update the style guide based on the learnings. Keep what works, change what the data says "
        "doesn't, and keep the channel recognizable. Return the full updated file.\n\n" + STYLE_TEMPLATE_HINT
    )
    guide = claude.text(SYSTEM, prompt)
    settings.style_guide_path.write_text(guide + "\n", encoding="utf-8")
    return guide
