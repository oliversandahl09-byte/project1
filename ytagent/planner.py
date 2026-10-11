"""Turns "what the user asked for" into a concrete run plan: how many videos, which niche, style wishes.

- With a free-text task ("make 3 videos about X in style Y"), Claude interprets it.
- Without a task, the agent rotates between the niches in brief.md, picking the one
  that has had the fewest videos lately.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .brief import Brief
from .llm import Claude
from .models import TaskInterpretation
from .prompts import SYSTEM


@dataclass
class RunPlan:
    count: int
    niche: str
    niche_description: str
    style_notes: str = ""
    task: str = ""

    def as_prompt(self) -> str:
        parts = [f"Niche for this run: {self.niche}", self.niche_description]
        if self.style_notes:
            parts.append(f"Style wishes for this run (apply within the style guide): {self.style_notes}")
        if self.task:
            parts.append(f"Original request from the channel owner: {self.task}")
        return "<this_run>\n" + "\n".join(p for p in parts if p) + "\n</this_run>"


def pick_niche_by_rotation(brief: Brief, history_items: list[dict]) -> tuple[str, str]:
    if not brief.niches:
        return "general", "Pick a topic that fits the brief and the audience."
    cutoff = datetime.now(timezone.utc) - timedelta(days=14)
    recent = Counter(
        h.get("niche", "") for h in history_items
        if h.get("created") and datetime.fromisoformat(h["created"]) >= cutoff
    )
    niche = min(brief.niches, key=lambda n: recent.get(n.name, 0))  # stable: first niche wins ties
    return niche.name, niche.description


def make_plan(brief: Brief, history_items: list[dict], claude: Claude | None,
              task: str = "", niche: str = "", count: int | None = None) -> RunPlan:
    if niche:
        found = brief.find_niche(niche)
        name, desc = (found.name, found.description) if found else (niche, "")
        plan = RunPlan(count or brief.video_count, name, desc, task=task)
    elif task:
        listed = "\n".join(f"- {n.name}: {n.description}" for n in brief.niches) or "(none)"
        parsed = claude.structured(
            SYSTEM,
            f"Niches in the brief:\n{listed}\n\nThe channel owner wrote (may be Swedish):\n<request>{task}</request>\n\n"
            "Interpret the request.",
            TaskInterpretation,
        )
        found = brief.find_niche(parsed.matches_existing_niche) if parsed.matches_existing_niche else None
        plan = RunPlan(
            count=count or parsed.count or brief.video_count,
            niche=found.name if found else parsed.niche,
            niche_description=(found.description + "\n" + parsed.niche_description).strip() if found else parsed.niche_description,
            style_notes=parsed.style_notes,
            task=task,
        )
    else:
        name, desc = pick_niche_by_rotation(brief, history_items)
        plan = RunPlan(count or brief.video_count, name, desc)
    plan.count = max(1, min(plan.count, brief.max_videos_per_run))
    return plan
