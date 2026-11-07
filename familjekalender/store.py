"""Logik för kalendrar, arbetspass och sammanslagna händelser."""

from __future__ import annotations

import sqlite3
import threading
from datetime import date, datetime, timedelta

from . import ical_sources
from .db import rows

_refresh_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()


def _now() -> str:
    return datetime.now(ical_sources.TZ).strftime("%Y-%m-%dT%H:%M")


# ---------------------------------------------------------------- kalendrar

def save_events(conn: sqlite3.Connection, calendar_id: int, events: list[dict]) -> None:
    with conn:
        conn.execute("DELETE FROM events WHERE calendar_id = ?", (calendar_id,))
        conn.executemany(
            "INSERT INTO events (calendar_id, uid, title, start, end, all_day, location, description)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (calendar_id, e["uid"], e["title"], e["start"], e["end"], int(e["all_day"]),
                 e["location"], e["description"])
                for e in events
            ],
        )
        conn.execute(
            "UPDATE calendars SET last_fetched = ?, last_error = NULL, event_count = ? WHERE id = ?",
            (_now(), len(events), calendar_id),
        )


def refresh_calendar(conn: sqlite3.Connection, calendar_id: int) -> dict:
    """Hämtar om en prenumererad kalender. Vid fel behålls gamla händelser."""
    with _locks_guard:
        lock = _refresh_locks.setdefault(calendar_id, threading.Lock())
    with lock:
        cal = conn.execute("SELECT * FROM calendars WHERE id = ?", (calendar_id,)).fetchone()
        if cal is None:
            raise ical_sources.CalendarError("Kalendern finns inte.")
        if cal["kind"] != "url":
            return dict(cal)
        try:
            data = ical_sources.fetch_ics(cal["url"])
            events = ical_sources.parse_events(data)
        except ical_sources.CalendarError as exc:
            with conn:
                conn.execute(
                    "UPDATE calendars SET last_error = ?, last_fetched = ? WHERE id = ?",
                    (str(exc), _now(), calendar_id),
                )
            raise
        save_events(conn, calendar_id, events)
        return dict(conn.execute("SELECT * FROM calendars WHERE id = ?", (calendar_id,)).fetchone())


def stale_calendars(conn: sqlite3.Connection, max_age_hours: float) -> list[int]:
    cutoff = (datetime.now(ical_sources.TZ) - timedelta(hours=max_age_hours)).strftime("%Y-%m-%dT%H:%M")
    return [
        r["id"]
        for r in conn.execute(
            "SELECT id FROM calendars WHERE kind = 'url' AND (last_fetched IS NULL OR last_fetched < ?)",
            (cutoff,),
        )
    ]


# ---------------------------------------------------------------- arbetspass

def shift_times(day: str, start_time: str | None, end_time: str | None) -> tuple[str, str, bool]:
    """Start/slut för ett pass. Slut före start betyder att passet går över midnatt."""
    if not start_time or not end_time:
        d = date.fromisoformat(day)
        return day, (d + timedelta(days=1)).isoformat(), True
    start = f"{day}T{start_time}"
    end_day = date.fromisoformat(day)
    if end_time <= start_time:
        end_day += timedelta(days=1)
    return start, f"{end_day.isoformat()}T{end_time}", False


def set_shift(conn: sqlite3.Connection, member_id: int, day: str, shift_type_id: int | None, note: str | None = None) -> None:
    date.fromisoformat(day)  # validerar
    with conn:
        if shift_type_id is None:
            conn.execute("DELETE FROM shifts WHERE member_id = ? AND date = ?", (member_id, day))
        else:
            conn.execute(
                "INSERT INTO shifts (member_id, date, shift_type_id, note) VALUES (?, ?, ?, ?)"
                " ON CONFLICT (member_id, date) DO UPDATE SET shift_type_id = excluded.shift_type_id,"
                " note = excluded.note",
                (member_id, day, shift_type_id, note),
            )


def repeat_shifts(conn: sqlite3.Connection, member_id: int, first_day: str, weeks: int, until: str) -> int:
    """Upprepar ett rullande schema: veckorna [first_day, first_day + weeks) kopieras framåt till och med `until`.

    Befintliga pass efter mönstret skrivs över (även lediga dagar i mönstret blir lediga).
    Returnerar antal pass som skapades.
    """
    if not 1 <= weeks <= 52:
        raise ValueError("Antal veckor måste vara 1–52.")
    start = date.fromisoformat(first_day)
    last = date.fromisoformat(until)
    period = weeks * 7
    pattern_end = start + timedelta(days=period)
    if last < pattern_end:
        raise ValueError("Slutdatum måste ligga efter mönstret.")
    if (last - pattern_end).days > 3 * 366:
        raise ValueError("Upprepa högst tre år framåt.")

    pattern = {
        r["date"]: (r["shift_type_id"], r["note"])
        for r in conn.execute(
            "SELECT date, shift_type_id, note FROM shifts WHERE member_id = ? AND date >= ? AND date < ?",
            (member_id, start.isoformat(), pattern_end.isoformat()),
        )
    }
    new_rows = []
    day = pattern_end
    while day <= last:
        src = start + timedelta(days=(day - start).days % period)
        if src.isoformat() in pattern:
            type_id, note = pattern[src.isoformat()]
            new_rows.append((member_id, day.isoformat(), type_id, note))
        day += timedelta(days=1)

    with conn:
        conn.execute(
            "DELETE FROM shifts WHERE member_id = ? AND date >= ? AND date <= ?",
            (member_id, pattern_end.isoformat(), last.isoformat()),
        )
        conn.executemany(
            "INSERT INTO shifts (member_id, date, shift_type_id, note) VALUES (?, ?, ?, ?)", new_rows
        )
    return len(new_rows)


# ---------------------------------------------------------------- sammanslaget

def events_between(conn: sqlite3.Connection, start: str, end: str, member_id: int | None = None) -> list[dict]:
    """Alla händelser (kalendrar + arbetspass) som överlappar [start, end)."""
    date.fromisoformat(start)
    date.fromisoformat(end)

    sql = (
        "SELECT e.id, e.title, e.start, e.end, e.all_day, e.location, e.description,"
        " c.id AS calendar_id, c.name AS calendar_name, c.member_id,"
        " COALESCE(c.color, m.color, '#6b7280') AS color"
        " FROM events e JOIN calendars c ON c.id = e.calendar_id"
        " LEFT JOIN members m ON m.id = c.member_id"
        " WHERE e.start < ? AND (e.end > ? OR (e.end = e.start AND e.start >= ?))"
    )
    params: list = [end, start, start]
    if member_id is not None:
        sql += " AND c.member_id = ?"
        params.append(member_id)
    result = []
    for r in rows(conn.execute(sql, params)):
        r["all_day"] = bool(r["all_day"])
        r["source"] = "calendar"
        r["key"] = f"c{r['id']}"
        result.append(r)

    # Pass som börjar dagen före kan gå över midnatt in i intervallet.
    day_before = (date.fromisoformat(start) - timedelta(days=1)).isoformat()
    sql = (
        "SELECT s.id, s.date, s.note, s.member_id, t.id AS shift_type_id, t.name, t.short,"
        " t.start_time, t.end_time, t.color"
        " FROM shifts s JOIN shift_types t ON t.id = s.shift_type_id"
        " WHERE s.date >= ? AND s.date < ?"
    )
    params = [day_before, end]
    if member_id is not None:
        sql += " AND s.member_id = ?"
        params.append(member_id)
    for r in rows(conn.execute(sql, params)):
        s, e, all_day = shift_times(r["date"], r["start_time"], r["end_time"])
        if not (s < end and e > start):
            continue
        result.append(
            {
                "id": r["id"],
                "key": f"s{r['id']}",
                "source": "shift",
                "title": r["name"],
                "short": r["short"],
                "start": s,
                "end": e,
                "all_day": all_day,
                "location": None,
                "description": r["note"],
                "member_id": r["member_id"],
                "shift_type_id": r["shift_type_id"],
                "date": r["date"],
                "calendar_id": None,
                "calendar_name": "Arbetsschema",
                "color": r["color"],
            }
        )
    result.sort(key=lambda e: (e["start"][:10], not e["all_day"], e["start"]))
    return result
