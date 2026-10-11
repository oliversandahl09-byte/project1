"""Fetches performance data for published videos (YouTube Data API + YouTube Analytics API).

Per video: views, likes, comments, shares, subs gained, watch time, average view duration/percentage,
retention curve -> hook retention (share still watching after ~3s and ~5s), end retention,
and thumbnail CTR when the API exposes it for the channel.
YouTube Analytics data lags 1-3 days, so videos younger than MIN_AGE are skipped.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from . import history
from .config import Settings
from .youtube import get_credentials

log = logging.getLogger(__name__)

MIN_AGE = timedelta(hours=48)
MAX_AGE = timedelta(days=60)
CORE_METRICS = ("views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,"
                "likes,comments,shares,subscribersGained")
CTR_METRICS = "videoThumbnailImpressions,videoThumbnailImpressionsClickRate"


def _published_at(item: dict) -> datetime | None:
    value = item.get("published_at") or item.get("publish_at")
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def eligible(items: list[dict], now: datetime) -> list[dict]:
    out = []
    for item in items:
        published = _published_at(item)
        if item.get("youtube_id") and item.get("status") in {"published", "scheduled"} and published:
            if MIN_AGE <= now - published <= MAX_AGE:
                out.append(item)
    return out


def retention_summary(rows: list[list[float]], duration: float) -> dict:
    """rows: [elapsedVideoTimeRatio, audienceWatchRatio, relativeRetentionPerformance] sorted by ratio."""
    if not rows or duration <= 0:
        return {}

    def at_seconds(sec: float) -> float:
        target = min(sec / duration, 1.0)
        return round(min(rows, key=lambda r: abs(r[0] - target))[1], 3)

    return {
        "retention_3s": at_seconds(3),
        "retention_5s": at_seconds(5),
        "retention_50pct": at_seconds(duration * 0.5),
        "retention_end": round(rows[-1][1], 3),
        "relative_retention": round(sum(r[2] for r in rows) / len(rows), 3),
    }


class AnalyticsClient:
    def __init__(self, settings: Settings):
        creds = get_credentials(settings, interactive=False)
        self.analytics = build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)
        self.data = build("youtube", "v3", credentials=creds, cache_discovery=False)
        self.ctr_supported = True

    def _query(self, **kw) -> dict:
        return self.analytics.reports().query(ids="channel==MINE", **kw).execute()

    @staticmethod
    def _rows(resp: dict) -> list[dict]:
        names = [h["name"] for h in resp.get("columnHeaders", [])]
        return [dict(zip(names, row)) for row in resp.get("rows", [])]

    def basic_stats(self, ids: list[str]) -> dict[str, dict]:
        out = {}
        for i in range(0, len(ids), 50):
            resp = self.data.videos().list(part="statistics", id=",".join(ids[i:i + 50])).execute()
            for v in resp.get("items", []):
                out[v["id"]] = {k: int(x) for k, x in v.get("statistics", {}).items() if str(x).isdigit()}
        return out

    def core(self, ids: list[str], start: str, end: str) -> dict[str, dict]:
        out = {}
        for i in range(0, len(ids), 200):
            resp = self._query(startDate=start, endDate=end, metrics=CORE_METRICS, dimensions="video",
                               filters="video==" + ",".join(ids[i:i + 200]), maxResults=200)
            for row in self._rows(resp):
                out[row.pop("video")] = row
        return out

    def ctr(self, ids: list[str], start: str, end: str) -> dict[str, dict]:
        if not self.ctr_supported:
            return {}
        try:
            resp = self._query(startDate=start, endDate=end, metrics=CTR_METRICS, dimensions="video",
                               filters="video==" + ",".join(ids[:200]), maxResults=200)
        except HttpError as e:
            log.info("CTR/visningar av thumbnail finns inte via API för kanalen (%s); fortsätter utan", e.resp.status)
            self.ctr_supported = False
            return {}
        return {row.pop("video"): row for row in self._rows(resp)}

    def retention(self, video_id: str, start: str, end: str) -> list[list[float]]:
        resp = self._query(startDate=start, endDate=end, dimensions="elapsedVideoTimeRatio",
                           metrics="audienceWatchRatio,relativeRetentionPerformance",
                           filters=f"video=={video_id}", sort="elapsedVideoTimeRatio")
        return resp.get("rows", [])


def refresh(settings: Settings, client: AnalyticsClient | None = None, now: datetime | None = None) -> list[dict]:
    """Fetch stats for eligible videos, store them in history and data/analytics.json."""
    now = now or datetime.now(timezone.utc)
    items = history.load(settings.history_path)
    targets = eligible(items, now)
    if not targets:
        log.info("Inga publicerade videos som är 2-60 dagar gamla ännu; ingen statistik att hämta")
        return []
    client = client or AnalyticsClient(settings)
    ids = [t["youtube_id"] for t in targets]
    start = min(_published_at(t) for t in targets).date().isoformat()
    end = now.date().isoformat()

    basic = client.basic_stats(ids)
    core = client.core(ids, start, end)
    ctr = client.ctr(ids, start, end)
    updated = []
    for item in targets:
        vid = item["youtube_id"]
        stats = {**basic.get(vid, {}), **core.get(vid, {}), **ctr.get(vid, {})}
        try:
            stats.update(retention_summary(client.retention(vid, start, end), float(item.get("duration", 0))))
        except HttpError as e:
            log.warning("Retention saknas för %s: %s", vid, e)
        stats["fetched_at"] = now.isoformat()
        item["stats"] = stats
        history.upsert(settings.history_path, item)
        updated.append(item)
        log.info("Statistik %s: %s visningar, %.0f%% snitt sett, hook 5s=%s",
                 vid, stats.get("views", "?"), float(stats.get("averageViewPercentage", 0) or 0),
                 stats.get("retention_5s", "?"))
    _save_snapshot(settings.data_dir / "analytics.json", updated)
    return updated


def _save_snapshot(path: Path, items: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(path.read_text()) if path.exists() else {}
    for item in items:
        data[item["youtube_id"]] = {"title": item.get("title"), "niche": item.get("niche"), **item["stats"]}
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
