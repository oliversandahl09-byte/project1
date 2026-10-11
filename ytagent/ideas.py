"""Step 1: come up with unique video ideas."""
from __future__ import annotations

from .llm import Claude
from .models import Idea, IdeaList
from .prompts import SYSTEM


def generate_ideas(claude: Claude, context: str, count: int, task: str = "") -> list[Idea]:
    extra = f"\nSpecific request for this run: {task}\n" if task else ""
    prompt = (
        f"{context}\n{extra}\n"
        f"Propose {count + 2} distinct Short ideas for this channel, then keep only the best {count}. "
        "Each must have a clear payoff, a distinct angle, and must not overlap with anything already made. "
        "Prefer ideas with a surprising or useful core that can be delivered in under a minute."
    )
    ideas = claude.structured(SYSTEM, prompt, IdeaList).ideas
    return ideas[:count]
