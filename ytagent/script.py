"""Step 2: write the script (hook, body, CTA) with visual cues per segment."""
from __future__ import annotations

from .llm import Claude
from .models import Idea, Script
from .prompts import SYSTEM


def write_script(claude: Claude, context: str, idea: Idea, target_seconds: int, language: str,
                 words_per_second: float = 2.5) -> Script:
    max_words = int(target_seconds * words_per_second)
    prompt = (
        f"{context}\n\n<idea>\n{idea.model_dump_json(indent=2)}\n</idea>\n\n"
        f"Write the script for this Short in {language}. Total narration: {max_words - 25}-{max_words} words "
        f"(about {target_seconds} seconds spoken calmly).\n"
        "Retention rules:\n"
        "- The hook is 8-14 words and creates curiosity or tension in the first 3 seconds. No greetings, no 'In this video'.\n"
        "- 4-7 body segments, each one short beat that moves the story forward; open a loop early and close it near the end.\n"
        "- Every segment gets a concrete, filmable stock-footage query (e.g. 'ocean waves aerial', not 'concept of time').\n"
        "- The CTA is one natural sentence that fits the style guide (follow, comment prompt, or part 2 tease).\n"
        "- Follow the style guide's tone, pacing and hook patterns, but do not reuse a hook pattern mechanically."
    )
    script = claude.structured(SYSTEM, prompt, Script)
    if not script.body:
        raise ValueError("Manuset saknar body-segment")
    return script
