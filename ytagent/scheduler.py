"""Publishing schedule: finds the next free publish slots from brief.md settings.

Slots are local times (publish_times, timezone) with at most max_per_day videos per day.
YouTube publishes a private video with publishAt automatically at that time.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .brief import Brief

LEAD_TIME = timedelta(hours=1)
PENDING = {"awaiting_approval", "scheduled"}


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def to_iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def taken_slots(history_items: list[dict]) -> list[datetime]:
    return [_parse_utc(h["publish_at"]) for h in history_items
            if h.get("publish_at") and h.get("status") in {"scheduled", "published"}]


def next_slots(brief: Brief, history_items: list[dict], n: int = 1, now: datetime | None = None) -> list[str]:
    tz = ZoneInfo(brief.timezone)
    now = now or datetime.now(timezone.utc)
    taken = taken_slots(history_items)
    taken_exact = {t.replace(second=0, microsecond=0) for t in taken}
    per_day = Counter(t.astimezone(tz).date() for t in taken)

    result: list[str] = []
    day = now.astimezone(tz).date()
    times = brief.publish_times
    for _ in range(366):
        # Alternate the starting time per day, so analytics can compare publish times.
        offset = day.toordinal() % len(times) if brief.max_per_day < len(times) else 0
        for hhmm in times[offset:] + times[:offset]:
            if len(result) == n:
                return result
            if per_day[day] >= brief.max_per_day:
                break
            h, m = (int(x) for x in hhmm.split(":"))
            slot = datetime(day.year, day.month, day.day, h, m, tzinfo=tz)
            slot_utc = slot.astimezone(timezone.utc)
            if slot_utc < now + LEAD_TIME or slot_utc in taken_exact:
                continue
            result.append(to_iso_utc(slot))
            taken_exact.add(slot_utc)
            per_day[day] += 1
        day += timedelta(days=1)
    return result


def videos_needed(brief: Brief, history_items: list[dict], now: datetime | None = None) -> int:
    """How many new videos keep the queue filled buffer_days ahead (used by `auto`)."""
    now = now or datetime.now(timezone.utc)
    waiting = 0
    for h in history_items:
        if h.get("status") == "awaiting_approval" or (h.get("status") == "rendered" and h.get("upload_pending")):
            waiting += 1
        elif h.get("status") == "scheduled" and h.get("publish_at") and _parse_utc(h["publish_at"]) > now:
            waiting += 1
    return max(0, brief.buffer_days * brief.max_per_day - waiting)
