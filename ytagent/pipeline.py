"""Runs the whole flow: brief -> ideas -> script -> voice -> footage -> edit -> packaging -> upload.

Each video is produced in isolation: if one fails, it is logged and the next one continues.
"""
from __future__ import annotations

import json
import logging
import re
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import history
from .brief import Brief, load_brief
from .config import Settings
from .editor import SegmentInput, render_short
from .ideas import generate_ideas
from .llm import Claude
from .media import fetch_clips
from .metadata import build_metadata
from .models import Idea
from .planner import RunPlan, make_plan
from .prompts import channel_context, read_optional
from .scheduler import next_slots
from .script import write_script
from .style import ensure_style_guide
from .thumbnail import choose_packaging
from .voice import synthesize_segments
from . import youtube

log = logging.getLogger(__name__)

MAX_SIMILARITY = 0.45
MAX_SHORT_SECONDS = 59.0


@dataclass
class RunResult:
    succeeded: list[dict] = field(default_factory=list)
    failed: list[dict] = field(default_factory=list)


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:50] or "video"


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


class Pipeline:
    def __init__(self, settings: Settings, claude: Claude | None = None):
        self.settings = settings
        self.claude = claude or Claude(settings)

    def _context(self, brief: Brief, plan: RunPlan) -> str:
        style = ensure_style_guide(self.settings, self.claude, brief.text)
        learnings = read_optional(self.settings.learnings_path)
        titles = [h.get("title", "") for h in history.load(self.settings.history_path) if h.get("title")]
        return channel_context(brief.text, style, learnings, titles, plan.as_prompt())

    def run(self, count: int | None = None, task: str = "", niche: str = "", upload: bool = True) -> RunResult:
        brief = load_brief(self.settings.brief_path)
        plan = make_plan(brief, history.load(self.settings.history_path), self.claude, task, niche, count)
        log.info("Plan: %d video(s), nisch '%s'%s", plan.count, plan.niche,
                 f", stil: {plan.style_notes}" if plan.style_notes else "")
        context = self._context(brief, plan)
        ideas = generate_ideas(self.claude, context, plan.count)
        log.info("%d idéer: %s", len(ideas), [i.title_working for i in ideas])

        result = RunResult()
        for idea in ideas:
            try:
                entry = self.produce(brief, context, idea, upload, plan)
                result.succeeded.append(entry)
            except Exception as e:  # one failed video must not stop the rest
                log.error("Video '%s' misslyckades: %s\n%s", idea.title_working, e, traceback.format_exc())
                result.failed.append({"idea": idea.title_working, "error": str(e)})
        return result

    def produce(self, brief: Brief, context: str, idea: Idea, upload: bool, plan: RunPlan) -> dict:
        s = self.settings
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        vid_id = f"{stamp}_{slugify(idea.title_working)}"
        work = s.output_dir / vid_id
        work.mkdir(parents=True, exist_ok=True)
        entry: dict = {"id": vid_id, "dir": str(work), "idea": idea.model_dump(), "status": "started",
                       "niche": plan.niche, "style_notes": plan.style_notes,
                       "created": datetime.now(timezone.utc).isoformat()}
        log.info("=== %s ===", idea.title_working)

        # Script
        script = write_script(self.claude, context, idea, brief.target_seconds, brief.language,
                              brief.words_per_second)
        similarity = history.max_similarity(script.full_text, history.load(s.history_path))
        if similarity > MAX_SIMILARITY:
            raise ValueError(f"Manuset liknar en tidigare video för mycket ({similarity:.0%}); hoppar över")
        _write_json(work / "script.json", script.model_dump())
        entry["script"] = script.full_text
        entry["hook"] = script.hook.narration

        # Voice
        segs = script.segments
        voices = synthesize_segments(s, [seg.narration for seg in segs], work / "audio")
        total = sum(d for _, d in voices)
        if total > MAX_SHORT_SECONDS:
            raise ValueError(f"Rösten blev {total:.1f}s, över {MAX_SHORT_SECONDS}s för en Short")

        # Footage
        clips = fetch_clips(s, [seg.visual_query for seg in segs], [d for _, d in voices], work / "footage")

        # Edit
        inputs = [SegmentInput(seg.narration, seg.on_screen_text, path, dur, clip)
                  for seg, (path, dur), clip in zip(segs, voices, clips)]
        video = render_short(inputs, work / "build", work / "final.mp4", s.music_dir, s.fonts_dir)

        # Title + thumbnail (3 variants, best one chosen)
        # Thumbnails use frames from the caption-free cut.
        clean = work / "build" / "video.mp4"
        variant, thumb, packaging = choose_packaging(self.claude, s, context, script, clean, total, work)
        _write_json(work / "packaging.json", packaging)

        # Description + tags
        meta = build_metadata(self.claude, context, script, variant.title, clips, s.ai_disclosure)
        _write_json(work / "metadata.json", {"title": variant.title, **meta.model_dump()})
        entry.update({"title": variant.title, "thumbnail_text": variant.thumbnail_text, "thumbnail": str(thumb),
                      "video": str(video), "duration": round(total, 1), "status": "rendered"})
        # Saved before upload, so a failed upload (e.g. quota) can be retried with `ytagent upload`.
        _write_json(work / "manifest.json", entry)
        history.upsert(s.history_path, entry)
        if upload:
            entry["upload_pending"] = True
            history.upsert(s.history_path, entry)
            entry = self.upload(brief, entry)
        return entry

    def upload(self, brief: Brief, entry: dict) -> dict:
        s = self.settings
        work = Path(entry["dir"])
        meta = json.loads((work / "metadata.json").read_text(encoding="utf-8"))

        # Without approval the video is scheduled for the next free slot right away.
        publish_at = None
        if not s.approval_required:
            publish_at = next_slots(brief, history.load(s.history_path), 1)[0]
        video_id = youtube.upload_video(
            s, Path(entry["video"]), meta["title"], meta["description"], meta["tags"], brief.category_id,
            language=brief.language_code, synthetic=s.ai_disclosure,
            made_for_kids=brief.made_for_kids, publish_at=publish_at,
        )
        entry["youtube_id"] = video_id
        entry["upload_pending"] = False
        entry["thumbnail_set"] = youtube.set_thumbnail(s, video_id, Path(entry["thumbnail"]))
        if publish_at:
            entry.update({"status": "scheduled", "publish_at": publish_at})
            log.info("Schemalagd %s: https://youtu.be/%s", publish_at, video_id)
        else:
            entry["status"] = "awaiting_approval"
            log.info("Väntar på godkännande. Titta: https://studio.youtube.com/video/%s/edit  "
                     "Godkänn: python -m ytagent approve %s", video_id, video_id)
        _write_json(work / "manifest.json", entry)
        history.upsert(s.history_path, entry)
        return entry
