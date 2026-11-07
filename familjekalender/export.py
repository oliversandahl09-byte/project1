"""Bygger en iCal-fil av familjekalendern så att den kan prenumereras på i mobilen."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import icalendar

from . import ical_sources
from .store import events_between


def _dt(value: str, all_day: bool):
    if all_day:
        return date.fromisoformat(value[:10])
    local = datetime.strptime(value, "%Y-%m-%dT%H:%M").replace(tzinfo=ical_sources.TZ)
    return local.astimezone(timezone.utc)


def build_feed(conn, member_id: int | None = None, name: str = "Familjekalender") -> bytes:
    members = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM members")}
    today = date.today()
    events = events_between(
        conn,
        (today - timedelta(days=60)).isoformat(),
        (today + timedelta(days=ical_sources.DAYS_AHEAD)).isoformat(),
        member_id,
    )

    cal = icalendar.Calendar()
    cal.add("prodid", "-//Familjekalender//SV")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("x-wr-calname", name)
    cal.add("x-wr-timezone", "Europe/Stockholm")
    cal.add("refresh-interval", timedelta(hours=1), parameters={"VALUE": "DURATION"})
    cal.add("x-published-ttl", "PT1H")

    stamp = datetime.now(timezone.utc)
    for e in events:
        ev = icalendar.Event()
        ev.add("uid", f"{e['key']}-{e['start']}@familjekalender")
        ev.add("dtstamp", stamp)
        who = members.get(e["member_id"])
        title = e["title"]
        if member_id is None and who:
            title = f"{who}: {title}"
        ev.add("summary", title)
        ev.add("dtstart", _dt(e["start"], e["all_day"]))
        ev.add("dtend", _dt(e["end"], e["all_day"]))
        if e.get("location"):
            ev.add("location", e["location"])
        if e.get("description"):
            ev.add("description", e["description"])
        ev.add("categories", [e["calendar_name"]])
        cal.add_component(ev)
    return cal.to_ical()
