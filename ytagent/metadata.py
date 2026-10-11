"""Step 7: description, tags and disclosure lines."""
from __future__ import annotations

from .llm import Claude
from .media import Clip
from .models import Metadata, Script
from .prompts import SYSTEM

AI_NOTE = "Narration uses an AI-generated voice. Script written with AI assistance and reviewed for accuracy."


def build_metadata(claude: Claude, context: str, script: Script, title: str,
                   clips: list[Clip], ai_disclosure: bool) -> Metadata:
    meta = claude.structured(
        SYSTEM,
        f"{context}\n\n<title>{title}</title>\n<script>\n{script.full_text}\n</script>\n"
        f"<notes>{script.sources_or_notes}</notes>\n\n"
        "Write the YouTube description (2-4 short lines plus 3-5 hashtags including #Shorts) and 10-15 tags. "
        "The first line should make people want to watch. Do not include credits; they are added automatically.",
        Metadata,
    )
    credits = sorted({c.credit for c in clips if c.credit})
    extra = []
    if script.sources_or_notes.strip():
        extra.append(f"Sources: {script.sources_or_notes.strip()}")
    if credits:
        extra.append("Footage: " + "; ".join(credits) + " (Pexels License).")
    if ai_disclosure:
        extra.append(AI_NOTE)
    description = meta.description.strip()
    if "#shorts" not in description.lower():
        description += " #Shorts"
    description = description + "\n\n" + "\n".join(extra)
    tags = [t.strip().lstrip("#") for t in meta.tags if t.strip()]
    # YouTube limits tags to 500 characters total.
    kept, total = [], 0
    for t in tags:
        if total + len(t) + 2 > 480:
            break
        kept.append(t)
        total += len(t) + 2
    return Metadata(description=description[:4900], tags=kept)
