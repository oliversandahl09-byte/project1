"""Hämtar och tolkar iCal-kalendrar (laget.se, förbundens matchkalendrar, jobbschema m.m.)."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import icalendar
import recurring_ical_events
import requests

TZ = ZoneInfo("Europe/Stockholm")
USER_AGENT = "Familjekalender/1.0 (+privat familjeapp)"

# Hur långt bakåt/framåt återkommande händelser räknas ut.
DAYS_BACK = 90
DAYS_AHEAD = 400


class CalendarError(Exception):
    """Fel som visas för användaren (på svenska)."""


def normalize_url(url: str) -> str:
    """webcal:// -> https://, lägger till https:// om schema saknas."""
    url = (url or "").strip()
    if not url:
        raise CalendarError("Ange en länk till kalendern.")
    if re.match(r"(?i)^webcals?://", url):
        url = "https://" + url.split("://", 1)[1]
    elif not re.match(r"(?i)^https?://", url):
        url = "https://" + url
    return url


def fetch_ics(url: str, timeout: float = 20) -> bytes:
    url = normalize_url(url)
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/calendar, */*"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise CalendarError(f"Kunde inte nå kalendern: {exc.__class__.__name__}") from exc
    if resp.status_code in (401, 403):
        raise CalendarError(
            "Kalendern kräver inloggning eller är privat. "
            "Använd prenumerationslänken (webcal/iCal), inte den vanliga webbsidan."
        )
    if resp.status_code == 404:
        raise CalendarError("Kalendern hittades inte (404). Kontrollera länken.")
    if resp.status_code >= 400:
        raise CalendarError(f"Servern svarade med fel {resp.status_code}.")
    return resp.content


def _to_local(value) -> tuple[str, bool]:
    """Returnerar (sträng, heldag) i lokal svensk tid."""
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(TZ)
        return value.strftime("%Y-%m-%dT%H:%M"), False
    if isinstance(value, date):
        return value.isoformat(), True
    raise ValueError(f"Okänt datumformat: {value!r}")


def _text(component, key: str, limit: int = 2000) -> str | None:
    val = component.get(key)
    if val is None:
        return None
    val = str(val).strip()
    return val[:limit] or None


def parse_events(data: bytes | str, window_start: date | None = None, window_end: date | None = None) -> list[dict]:
    """Tolkar en iCal-fil och returnerar händelser (återkommande utvecklade) inom fönstret."""
    if isinstance(data, bytes):
        head = data[:2000].lstrip(b"\xef\xbb\xbf").lstrip()
    else:
        head = data[:2000].lstrip("﻿").lstrip().encode()
    if not head.upper().startswith(b"BEGIN:VCALENDAR"):
        raise CalendarError(
            "Länken gav ingen kalenderfil (iCal). Leta efter 'Prenumerera', 'iCal' eller "
            "'Exportera kalender' och kopiera den länken."
        )
    try:
        cal = icalendar.Calendar.from_ical(data)
    except Exception as exc:  # noqa: BLE001 - trasiga filer finns i det vilda
        raise CalendarError("Kalenderfilen gick inte att läsa (trasig iCal).") from exc

    today = date.today()
    window_start = window_start or today - timedelta(days=DAYS_BACK)
    window_end = window_end or today + timedelta(days=DAYS_AHEAD)

    try:
        occurrences = recurring_ical_events.of(cal).between(window_start, window_end)
    except Exception as exc:  # noqa: BLE001
        raise CalendarError("Kunde inte räkna ut återkommande händelser i kalendern.") from exc

    events: list[dict] = []
    for comp in occurrences:
        if comp.name != "VEVENT" or comp.get("DTSTART") is None:
            continue
        dtstart = comp.get("DTSTART").dt
        if comp.get("DTEND") is not None:
            dtend = comp.get("DTEND").dt
        elif comp.get("DURATION") is not None:
            dtend = dtstart + comp.get("DURATION").dt
        elif isinstance(dtstart, datetime):
            dtend = dtstart
        else:
            dtend = dtstart + timedelta(days=1)

        start, all_day = _to_local(dtstart)
        end, _ = _to_local(dtend)
        if all_day and isinstance(dtend, datetime):
            end = dtend.date().isoformat()
        if not all_day and isinstance(dtend, date) and not isinstance(dtend, datetime):
            end = dtend.isoformat() + "T00:00"
        if end < start:
            end = start

        title = _text(comp, "SUMMARY", 300) or "(utan titel)"
        if str(comp.get("STATUS", "")).upper() == "CANCELLED":
            title = "INSTÄLLT: " + title

        events.append(
            {
                "uid": _text(comp, "UID", 500),
                "title": title,
                "start": start,
                "end": end,
                "all_day": all_day,
                "location": _text(comp, "LOCATION", 500),
                "description": _text(comp, "DESCRIPTION"),
            }
        )
    events.sort(key=lambda e: e["start"])
    return events


def calendar_name(data: bytes | str) -> str | None:
    """Kalenderns eget namn (X-WR-CALNAME) om det finns, för att föreslå ett namn."""
    try:
        cal = icalendar.Calendar.from_ical(data)
    except Exception:  # noqa: BLE001
        return None
    name = cal.get("X-WR-CALNAME")
    return str(name).strip() or None if name else None
