"""Turns statistics into lessons: writes learnings.md and updates style_guide.md."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from . import history
from .brief import Brief
from .config import Settings
from .llm import Claude
from .models import Lessons
from .prompts import SYSTEM, read_optional
from .style import update_style_guide

log = logging.getLogger(__name__)

MIN_VIDEOS_FOR_LESSONS = 3
FEATURES = ("title", "niche", "hook", "thumbnail_text", "style_notes", "duration", "publish_at", "published_at")
STAT_KEYS = ("views", "averageViewPercentage", "averageViewDuration", "retention_3s", "retention_5s",
             "retention_50pct", "retention_end", "relative_retention", "likes", "comments", "shares",
             "subscribersGained", "videoThumbnailImpressions", "videoThumbnailImpressionsClickRate")


def _rows(items: list[dict]) -> list[dict]:
    rows = []
    for item in items:
        stats = item.get("stats") or {}
        if not stats:
            continue
        row = {k: item.get(k) for k in FEATURES if item.get(k) is not None}
        row.update({k: stats[k] for k in STAT_KEYS if k in stats})
        rows.append(row)
    return rows


def render_markdown(lessons: Lessons, n_videos: int) -> str:
    def bullets(items: list[str]) -> str:
        return "\n".join(f"- {x}" for x in items) or "- (inget ännu)"

    return (
        f"# Learnings\n\n_Uppdaterad {datetime.now(timezone.utc):%Y-%m-%d} från {n_videos} videos. "
        f"Säkerhet: {lessons.confidence}._\n\n"
        f"## Summary\n{lessons.summary}\n\n"
        f"## What works\n{bullets(lessons.what_works)}\n\n"
        f"## What doesn't\n{bullets(lessons.what_doesnt)}\n\n"
        f"## Per niche\n{bullets(lessons.per_niche)}\n\n"
        f"## Experiments for the next videos\n{bullets(lessons.experiments)}\n"
    )


def update_learnings(settings: Settings, claude: Claude, brief: Brief) -> str | None:
    rows = _rows(history.load(settings.history_path))
    if len(rows) < MIN_VIDEOS_FOR_LESSONS:
        log.info("Bara %d videos med statistik; väntar till %d innan lärdomar dras", len(rows), MIN_VIDEOS_FOR_LESSONS)
        return None
    previous = read_optional(settings.learnings_path)
    prompt = (
        f"<brief>\n{brief.text}\n</brief>\n\n<previous_learnings>\n{previous}\n</previous_learnings>\n\n"
        f"<video_performance>\n{json.dumps(rows, indent=1, ensure_ascii=False)}\n</video_performance>\n\n"
        "These are YouTube Shorts. Key signals, in order: retention_3s/retention_5s (did the hook stop the swipe; "
        "Shorts loops can push values above 1.0), averageViewPercentage, retention_end, shares and subscribersGained "
        "per view, then views. CTR fields may be missing; for Shorts the feed matters more than thumbnails.\n"
        "Compare videos against each other and find patterns in hooks, topics, niches, titles, length and publish "
        "times. Be specific and cite the videos as evidence. Do not overfit: with few videos, say so and keep "
        "conclusions tentative. Keep what earlier learnings got right unless new data contradicts them."
    )
    lessons = claude.structured(SYSTEM, prompt, Lessons)
    text = render_markdown(lessons, len(rows))
    settings.learnings_path.write_text(text, encoding="utf-8")
    log.info("learnings.md uppdaterad (%d videos)", len(rows))
    update_style_guide(settings, claude, brief.text)
    log.info("style_guide.md uppdaterad utifrån lärdomarna")
    return text
