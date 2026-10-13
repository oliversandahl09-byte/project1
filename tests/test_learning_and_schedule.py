"""Tests for niches/planning, scheduling, analytics parsing, learning, and upload/approval flow."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ytagent import analytics, history, learn, pipeline, scheduler
from ytagent.brief import parse_brief
from ytagent.config import Settings
from ytagent.planner import make_plan, pick_niche_by_rotation

from test_pipeline import BRIEF, FakeClaude, fake_clips, fake_voice

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)  # 14:00 in Stockholm


def brief(extra: str = ""):
    return parse_brief(BRIEF + extra)


def test_niches_parsed_and_capped():
    b = parse_brief(BRIEF + "\n## Niches\n### A\nx\n### B\ny\n### C\nz\n### D\nw\n")
    assert [n.name for n in parse_brief(BRIEF).niches] == ["Deep ocean", "Space"]
    assert len(b.niches) <= 3


def test_rotation_picks_least_used_niche():
    items = [{"niche": "Deep ocean", "created": datetime.now(timezone.utc).isoformat()}]
    assert pick_niche_by_rotation(brief(), items)[0] == "Space"


def test_free_text_task_is_interpreted():
    plan = make_plan(brief(), [], FakeClaude(), task="gör 3 videos om svarta hål i mystisk stil")
    assert plan.count == 3 and plan.niche == "Space" and plan.style_notes == "mysterious"
    assert "svarta hål" in plan.as_prompt()


def test_count_is_capped():
    assert make_plan(brief(), [], None, niche="space", count=50).count == 5


def test_next_slots_respect_times_and_daily_limit():
    b = brief("- timezone: Europe/Stockholm\n- publish_times: 16:00, 19:30\n- max_per_day: 1\n")
    slots = scheduler.next_slots(b, [], 4, now=NOW)
    assert [s[:10] for s in slots] == ["2026-10-11", "2026-10-12", "2026-10-13", "2026-10-14"]  # one per day
    assert {s[11:16] for s in slots} == {"14:00", "17:30"}  # both publish times get used
    taken = [{"status": "scheduled", "publish_at": slots[0]}]
    assert scheduler.next_slots(b, taken, 1, now=NOW) == [slots[1]]


def test_two_per_day_and_lead_time():
    b = brief("- publish_times: 16:00, 19:30\n- max_per_day: 2\n")
    late = NOW.replace(hour=13, minute=30)  # 15:30 local: 16:00 is within the 1h lead time
    assert scheduler.next_slots(b, [], 2, now=late) == ["2026-10-11T17:30:00Z", "2026-10-12T14:00:00Z"]


def test_videos_needed_counts_queue():
    b = brief("- buffer_days: 3\n- max_per_day: 1\n")
    items = [{"status": "awaiting_approval"},
             {"status": "scheduled", "publish_at": "2026-10-20T14:00:00Z"},
             {"status": "scheduled", "publish_at": "2026-10-01T14:00:00Z"}]
    assert scheduler.videos_needed(b, items, now=NOW) == 1


def test_retention_summary():
    rows = [[i / 100, 1.2 - i / 100, 0.5] for i in range(0, 101)]
    r = analytics.retention_summary(rows, duration=40)
    assert abs(r["retention_3s"] - 1.125) < 0.01  # 3s of 40s = 7.5% into the video
    assert r["retention_end"] == 0.2 and r["relative_retention"] == 0.5


class FakeAnalytics:
    ctr_supported = False

    def basic_stats(self, ids):
        return {i: {"viewCount": 100} for i in ids}

    def core(self, ids, start, end):
        return {i: {"views": 100 + n * 50, "averageViewPercentage": 70 + n} for n, i in enumerate(ids)}

    def ctr(self, ids, start, end):
        return {}

    def retention(self, vid, start, end):
        return [[0.0, 1.0, 0.5], [0.1, 0.8, 0.6], [1.0, 0.4, 0.5]]


def test_analytics_refresh_and_learning(tmp_path: Path):
    (tmp_path / "brief.md").write_text(BRIEF)
    settings = Settings(root=tmp_path)
    old = (NOW - timedelta(days=5)).isoformat()
    for n in range(3):
        history.upsert(settings.history_path, {"id": f"v{n}", "youtube_id": f"yt{n}", "status": "published",
                                               "published_at": old, "duration": 40, "title": f"T{n}", "niche": "Space"})
    history.upsert(settings.history_path, {"id": "new", "youtube_id": "ytnew", "status": "published",
                                           "published_at": NOW.isoformat(), "duration": 40})
    updated = analytics.refresh(settings, client=FakeAnalytics(), now=NOW)
    assert [u["youtube_id"] for u in updated] == ["yt0", "yt1", "yt2"]  # too-new video skipped
    assert updated[0]["stats"]["retention_5s"] == 0.8
    assert json.loads((tmp_path / "data" / "analytics.json").read_text())["yt1"]["views"] == 150

    settings.style_guide_path.write_text("# Style guide\nold")
    text = learn.update_learnings(settings, FakeClaude(), brief())
    assert "question hooks" in text and settings.learnings_path.exists()
    assert "Calm deep-sea channel" in settings.style_guide_path.read_text()  # guide revised


def test_learning_waits_for_enough_data(tmp_path: Path):
    settings = Settings(root=tmp_path)
    assert learn.update_learnings(settings, FakeClaude(), brief()) is None


def _setup(tmp_path, monkeypatch, approval: bool):
    (tmp_path / "brief.md").write_text(BRIEF.replace("videos_per_run: 2", "videos_per_run: 1"))
    settings = Settings(root=tmp_path, approval_required=approval)
    monkeypatch.setattr(pipeline, "synthesize_segments", fake_voice)
    monkeypatch.setattr(pipeline, "fetch_clips", fake_clips)
    uploads = []
    monkeypatch.setattr(pipeline.youtube, "upload_video",
                        lambda s, video, title, desc, tags, cat, **kw: uploads.append(kw) or "YT123")
    monkeypatch.setattr(pipeline.youtube, "set_thumbnail", lambda *a: True)
    return settings, uploads


def test_upload_waits_for_approval(tmp_path, monkeypatch):
    settings, uploads = _setup(tmp_path, monkeypatch, approval=True)
    entry = pipeline.Pipeline(settings, claude=FakeClaude()).run().succeeded[0]
    assert entry["status"] == "awaiting_approval" and uploads[0]["publish_at"] is None
    assert entry["niche"] == "Deep ocean" and entry["hook"]


def test_autonomous_mode_schedules(tmp_path, monkeypatch):
    settings, uploads = _setup(tmp_path, monkeypatch, approval=False)
    entry = pipeline.Pipeline(settings, claude=FakeClaude()).run().succeeded[0]
    assert entry["status"] == "scheduled" and entry["publish_at"].endswith("Z")
    assert uploads[0]["publish_at"] == entry["publish_at"]


def test_failed_upload_can_be_retried(tmp_path, monkeypatch):
    settings, uploads = _setup(tmp_path, monkeypatch, approval=True)

    def boom(*a, **kw):
        raise RuntimeError("quotaExceeded")

    monkeypatch.setattr(pipeline.youtube, "upload_video", boom)
    result = pipeline.Pipeline(settings, claude=FakeClaude()).run()
    assert result.failed and "quota" in result.failed[0]["error"]
    saved = history.load(settings.history_path)[0]
    assert saved["status"] == "rendered" and saved["upload_pending"]
    assert scheduler.videos_needed(brief(), [saved]) == 2  # pending upload counts toward the queue

    monkeypatch.setattr(pipeline.youtube, "upload_video", lambda *a, **kw: "YT999")
    p = pipeline.Pipeline(settings, claude=FakeClaude())
    done = p.upload(parse_brief(BRIEF), saved)
    assert done["youtube_id"] == "YT999" and not done["upload_pending"]


def test_link_manual_upload_makes_video_trackable(tmp_path: Path):
    from ytagent.cli import link_video

    settings = Settings(root=tmp_path)
    history.upsert(settings.history_path, {"id": "v1", "youtube_id": "LOCKED1", "status": "awaiting_approval",
                                           "duration": 40, "title": "T"})
    when = NOW - timedelta(days=3)
    item = link_video(settings, "LOCKED1", "MANUAL1", now=when)
    assert item["youtube_id"] == "MANUAL1" and item["status"] == "published"
    assert [i["youtube_id"] for i in analytics.eligible(history.load(settings.history_path), NOW)] == ["MANUAL1"]
