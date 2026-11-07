from datetime import date

import icalendar
import pytest

from familjekalender import ical_sources, store
from familjekalender.app import create_app

LAGET_ICS = b"""BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//test//laget//SV\r
X-WR-CALNAME:P2014 Fotboll\r
BEGIN:VTIMEZONE\r
TZID:W. Europe Standard Time\r
BEGIN:STANDARD\r
DTSTART:16010101T030000\r
TZOFFSETFROM:+0200\r
TZOFFSETTO:+0100\r
RRULE:FREQ=YEARLY;BYDAY=-1SU;BYMONTH=10\r
END:STANDARD\r
BEGIN:DAYLIGHT\r
DTSTART:16010101T020000\r
TZOFFSETFROM:+0100\r
TZOFFSETTO:+0200\r
RRULE:FREQ=YEARLY;BYDAY=-1SU;BYMONTH=3\r
END:DAYLIGHT\r
END:VTIMEZONE\r
BEGIN:VEVENT\r
UID:match-1\r
SUMMARY:Match mot IFK\r
LOCATION:Valhalla IP\r
DTSTART:20261114T090000Z\r
DTEND:20261114T103000Z\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:traning\r
SUMMARY:Tr\xc3\xa4ning\r
DTSTART;TZID=W. Europe Standard Time:20261110T173000\r
DTEND;TZID=W. Europe Standard Time:20261110T190000\r
RRULE:FREQ=WEEKLY;COUNT=3\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:cup\r
SUMMARY:Cup\r
DTSTART;VALUE=DATE:20261121\r
DTEND;VALUE=DATE:20261123\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:inst\r
SUMMARY:Tr\xc3\xa4ningsmatch\r
STATUS:CANCELLED\r
DTSTART:20261115T100000\r
END:VEVENT\r
END:VCALENDAR\r
"""

W0, W1 = date(2026, 11, 1), date(2027, 1, 1)


def test_normalize_url():
    assert ical_sources.normalize_url("webcal://www.laget.se/x/ical") == "https://www.laget.se/x/ical"
    assert ical_sources.normalize_url(" laget.se/x.ics ") == "https://laget.se/x.ics"
    assert ical_sources.normalize_url("http://a.se/k.ics") == "http://a.se/k.ics"
    with pytest.raises(ical_sources.CalendarError):
        ical_sources.normalize_url("  ")


def test_parse_events_timezones_recurrence_allday_cancelled():
    events = ical_sources.parse_events(LAGET_ICS, W0, W1)
    by_title = {}
    for e in events:
        by_title.setdefault(e["title"], []).append(e)

    match = by_title["Match mot IFK"][0]
    assert (match["start"], match["end"]) == ("2026-11-14T10:00", "2026-11-14T11:30")  # UTC -> svensk tid
    assert match["location"] == "Valhalla IP"

    trainings = by_title["Träning"]
    assert [t["start"] for t in trainings] == ["2026-11-10T17:30", "2026-11-17T17:30", "2026-11-24T17:30"]

    cup = by_title["Cup"][0]
    assert cup["all_day"] and (cup["start"], cup["end"]) == ("2026-11-21", "2026-11-23")

    cancelled = by_title["INSTÄLLT: Träningsmatch"][0]
    assert cancelled["start"] == cancelled["end"] == "2026-11-15T10:00"
    assert ical_sources.calendar_name(LAGET_ICS) == "P2014 Fotboll"


def test_parse_rejects_html():
    with pytest.raises(ical_sources.CalendarError, match="ingen kalenderfil"):
        ical_sources.parse_events(b"<!doctype html><html>laget.se</html>")


def test_shift_times_overnight_and_allday():
    assert store.shift_times("2026-11-07", "21:30", "07:00") == ("2026-11-07T21:30", "2026-11-08T07:00", False)
    assert store.shift_times("2026-11-07", "07:00", "16:00") == ("2026-11-07T07:00", "2026-11-07T16:00", False)
    assert store.shift_times("2026-12-31", None, None) == ("2026-12-31", "2027-01-01", True)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("FAMILJEKALENDER_LOSENORD", raising=False)
    monkeypatch.setattr(ical_sources, "fetch_ics", lambda url, timeout=20: LAGET_ICS)
    monkeypatch.setattr(ical_sources, "DAYS_BACK", 3650)
    app = create_app(tmp_path / "test.db", background_refresh=False)
    return app.test_client()


def test_full_flow(client):
    mamma = client.post("/api/members", json={"name": "Anna", "color": "#DB2777"}).get_json()
    barn = client.post("/api/members", json={"name": "Wilma", "color": "#2563eb"}).get_json()
    assert mamma["color"] == "#db2777"

    cal = client.post("/api/calendars", json={"url": "webcal://laget.se/p2014/ical", "member_id": barn["id"]})
    assert cal.status_code == 201, cal.get_json()
    cal = cal.get_json()
    assert cal["name"] == "P2014 Fotboll" and cal["url"].startswith("https://") and cal["event_count"] == 6

    natt = client.post("/api/shift-types", json={
        "member_id": mamma["id"], "name": "Natt", "short": "N", "start_time": "21:30", "end_time": "07:00", "color": "#6d28d9",
    }).get_json()
    assert client.put("/api/shifts", json={"member_id": mamma["id"], "date": "2026-11-13", "shift_type_id": natt["id"]}).status_code == 200

    # Nattpasset 13/11 syns även när man frågar efter 14/11.
    events = client.get("/api/events?start=2026-11-14&end=2026-11-15").get_json()
    titles = {(e["source"], e["title"]) for e in events}
    assert ("shift", "Natt") in titles and ("calendar", "Match mot IFK") in titles

    only_wilma = client.get(f"/api/events?start=2026-11-01&end=2026-12-01&member_id={barn['id']}").get_json()
    assert only_wilma and all(e["member_id"] == barn["id"] for e in only_wilma)

    # Passtyp för fel person avvisas.
    r = client.put("/api/shifts", json={"member_id": barn["id"], "date": "2026-11-13", "shift_type_id": natt["id"]})
    assert r.status_code == 400

    # Ta bort pass.
    client.put("/api/shifts", json={"member_id": mamma["id"], "date": "2026-11-13", "shift_type_id": None})
    assert client.get(f"/api/shifts?member_id={mamma['id']}&start=2026-11-01&end=2026-12-01").get_json() == []

    # Felaktig länk ger begriplig felkod.
    r = client.post("/api/shift-types", json={"member_id": mamma["id"], "name": "X", "start_time": "25:00", "end_time": "07:00"})
    assert r.status_code == 400


def test_repeat_rolling_schedule(client):
    m = client.post("/api/members", json={"name": "Anna"}).get_json()
    dag = client.post("/api/shift-types", json={"member_id": m["id"], "name": "Dag", "start_time": "07:00", "end_time": "16:00"}).get_json()
    kvall = client.post("/api/shift-types", json={"member_id": m["id"], "name": "Kväll", "start_time": "14:00", "end_time": "22:00"}).get_json()
    # 2-veckorsmönster med start måndag 2 nov 2026: mån dag, tis kväll (v1), ons dag (v2).
    for d, t in [("2026-11-02", dag), ("2026-11-03", kvall), ("2026-11-11", dag)]:
        client.put("/api/shifts", json={"member_id": m["id"], "date": d, "shift_type_id": t["id"]})
    # Ett gammalt pass efter mönstret ska skrivas över (bli ledigt).
    client.put("/api/shifts", json={"member_id": m["id"], "date": "2026-11-19", "shift_type_id": dag["id"]})

    r = client.post("/api/shifts/repeat", json={"member_id": m["id"], "start": "2026-11-02", "weeks": 2, "until": "2026-11-29"})
    assert r.get_json() == {"created": 3}
    shifts = client.get(f"/api/shifts?member_id={m['id']}&start=2026-11-16&end=2026-12-01").get_json()
    assert [(s["date"], s["shift_type_id"]) for s in shifts] == [
        ("2026-11-16", dag["id"]), ("2026-11-17", kvall["id"]), ("2026-11-25", dag["id"]),
    ]

    bad = client.post("/api/shifts/repeat", json={"member_id": m["id"], "start": "2026-11-02", "weeks": 2, "until": "2026-11-10"})
    assert bad.status_code == 400


def test_upload_and_feed(client):
    m = client.post("/api/members", json={"name": "Anna"}).get_json()
    up = client.post(
        "/api/calendars/upload",
        data={"file": (__import__("io").BytesIO(LAGET_ICS), "lag.ics"), "member_id": str(m["id"])},
        content_type="multipart/form-data",
    )
    assert up.status_code == 201 and up.get_json()["kind"] == "file"

    t = client.post("/api/shift-types", json={"member_id": m["id"], "name": "Dag", "start_time": "07:00", "end_time": "16:00"}).get_json()
    client.put("/api/shifts", json={"member_id": m["id"], "date": date.today().isoformat(), "shift_type_id": t["id"]})

    feed = client.get("/kalender.ics")
    assert feed.status_code == 200 and feed.mimetype == "text/calendar"
    cal = icalendar.Calendar.from_ical(feed.data)
    summaries = [str(e["SUMMARY"]) for e in cal.walk("VEVENT")]
    assert "Anna: Dag" in summaries

    member_feed = icalendar.Calendar.from_ical(client.get(f"/kalender/{m['id']}.ics").data)
    assert "Dag" in [str(e["SUMMARY"]) for e in member_feed.walk("VEVENT")]


def test_password(tmp_path, monkeypatch):
    monkeypatch.setenv("FAMILJEKALENDER_LOSENORD", "hemligt")
    c = create_app(tmp_path / "pw.db", background_refresh=False).test_client()
    assert c.get("/api/members").status_code == 401
    import base64
    ok = {"Authorization": "Basic " + base64.b64encode(b"familj:hemligt").decode()}
    assert c.get("/api/members", headers=ok).status_code == 200
    assert c.get("/kalender.ics?nyckel=hemligt").status_code == 200
    assert c.get("/kalender.ics?nyckel=fel").status_code == 401


def test_bad_url_error_kept(client, monkeypatch):
    def boom(url, timeout=20):
        raise ical_sources.CalendarError("Kalendern hittades inte (404). Kontrollera länken.")
    cal = client.post("/api/calendars", json={"url": "https://laget.se/x"}).get_json()
    monkeypatch.setattr(ical_sources, "fetch_ics", boom)
    r = client.post(f"/api/calendars/{cal['id']}/refresh")
    assert r.status_code == 422 and "404" in r.get_json()["error"]
    after = client.get("/api/calendars").get_json()[0]
    assert after["last_error"] and after["event_count"] == 6  # gamla händelser finns kvar
