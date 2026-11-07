"""Webbserver för familjekalendern (Flask)."""

from __future__ import annotations

import base64
import hmac
import logging
import os
import re
import sqlite3
import threading
import time
from datetime import date, timedelta
from pathlib import Path

from flask import Flask, Response, abort, g, jsonify, request, send_from_directory

from . import db, export, ical_sources, store

log = logging.getLogger("familjekalender")
STATIC = Path(__file__).parent / "static"
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class BadRequest(Exception):
    pass


def _color(value, default: str | None = None) -> str | None:
    if value in (None, ""):
        return default
    if not isinstance(value, str) or not COLOR_RE.match(value):
        raise BadRequest("Ogiltig färg.")
    return value.lower()


def _text(value, field: str, max_len: int = 200, required: bool = True) -> str | None:
    value = (value or "").strip() if isinstance(value, str) or value is None else str(value)
    if not value:
        if required:
            raise BadRequest(f"{field} saknas.")
        return None
    return value[:max_len]


def _int_or_none(value) -> int | None:
    if value in (None, "", "null"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise BadRequest("Ogiltigt id.") from None


def _time(value) -> str | None:
    if value in (None, ""):
        return None
    if not TIME_RE.match(str(value)):
        raise BadRequest("Ange tid som TT:MM, t.ex. 07:00.")
    return str(value)


def _date(value, field: str = "Datum") -> str:
    try:
        return date.fromisoformat(str(value)).isoformat()
    except (TypeError, ValueError):
        raise BadRequest(f"{field} måste vara ÅÅÅÅ-MM-DD.") from None


def create_app(db_file: str | Path | None = None, background_refresh: bool = True) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config["DB_FILE"] = str(db_file or db.db_path())
    app.config["PASSWORD"] = os.environ.get("FAMILJEKALENDER_LOSENORD", "")
    app.config["REFRESH_HOURS"] = float(os.environ.get("FAMILJEKALENDER_UPPDATERA_TIMMAR", "3"))
    app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

    init_conn = db.connect(app.config["DB_FILE"])
    db.init(init_conn)
    init_conn.close()

    def conn() -> sqlite3.Connection:
        if "conn" not in g:
            g.conn = db.connect(app.config["DB_FILE"])
        return g.conn

    @app.teardown_appcontext
    def _close(_exc):
        c = g.pop("conn", None)
        if c is not None:
            c.close()

    # ------------------------------------------------------------ inloggning (valfri)

    @app.before_request
    def _auth():
        password = app.config["PASSWORD"]
        if not password:
            return None
        if request.path.endswith(".ics") and hmac.compare_digest(request.args.get("nyckel", ""), password):
            return None
        header = request.headers.get("Authorization", "")
        if header.startswith("Basic "):
            try:
                _user, _, given = base64.b64decode(header[6:]).decode().partition(":")
            except Exception:  # noqa: BLE001
                given = ""
            if hmac.compare_digest(given, password):
                return None
        return Response(
            "Lösenord krävs", 401, {"WWW-Authenticate": 'Basic realm="Familjekalender", charset="UTF-8"'}
        )

    @app.errorhandler(BadRequest)
    def _bad(exc):
        return jsonify(error=str(exc)), 400

    @app.errorhandler(ical_sources.CalendarError)
    def _cal_err(exc):
        return jsonify(error=str(exc)), 422

    def body() -> dict:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise BadRequest("Förväntade JSON.")
        return data

    def one(sql: str, *params) -> dict:
        row = conn().execute(sql, params).fetchone()
        if row is None:
            abort(404)
        return dict(row)

    # ------------------------------------------------------------ sidor

    @app.get("/")
    def index():
        resp = send_from_directory(STATIC, "index.html")
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    @app.get("/static/<path:name>")
    def static_file(name):
        resp = send_from_directory(STATIC, name)
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    @app.get("/manifest.webmanifest")
    def manifest():
        return send_from_directory(STATIC, "manifest.webmanifest", mimetype="application/manifest+json")

    # ------------------------------------------------------------ familjemedlemmar

    @app.get("/api/members")
    def list_members():
        return jsonify(db.rows(conn().execute("SELECT * FROM members ORDER BY id")))

    @app.post("/api/members")
    def add_member():
        data = body()
        name = _text(data.get("name"), "Namn", 60)
        color = _color(data.get("color"), "#2563eb")
        with conn():
            cur = conn().execute("INSERT INTO members (name, color) VALUES (?, ?)", (name, color))
        return jsonify(one("SELECT * FROM members WHERE id = ?", cur.lastrowid)), 201

    @app.put("/api/members/<int:mid>")
    def update_member(mid):
        current = one("SELECT * FROM members WHERE id = ?", mid)
        data = body()
        name = _text(data.get("name", current["name"]), "Namn", 60)
        color = _color(data.get("color"), current["color"])
        with conn():
            conn().execute("UPDATE members SET name = ?, color = ? WHERE id = ?", (name, color, mid))
        return jsonify(one("SELECT * FROM members WHERE id = ?", mid))

    @app.delete("/api/members/<int:mid>")
    def delete_member(mid):
        with conn():
            conn().execute("DELETE FROM members WHERE id = ?", (mid,))
        return "", 204

    # ------------------------------------------------------------ kalendrar

    def calendar_json(cid: int) -> dict:
        return one(
            "SELECT id, name, kind, url, member_id, color, last_fetched, last_error, event_count"
            " FROM calendars WHERE id = ?",
            cid,
        )

    @app.get("/api/calendars")
    def list_calendars():
        return jsonify(db.rows(conn().execute(
            "SELECT id, name, kind, url, member_id, color, last_fetched, last_error, event_count"
            " FROM calendars ORDER BY id"
        )))

    @app.post("/api/calendars")
    def add_calendar():
        data = body()
        url = ical_sources.normalize_url(_text(data.get("url"), "Länk", 2000))
        member_id = _int_or_none(data.get("member_id"))
        color = _color(data.get("color"))
        # Hämta först så att användaren direkt ser om länken fungerar.
        raw = ical_sources.fetch_ics(url)
        events = ical_sources.parse_events(raw)
        name = _text(data.get("name"), "Namn", 100, required=False) or ical_sources.calendar_name(raw) or "Kalender"
        with conn():
            cur = conn().execute(
                "INSERT INTO calendars (name, kind, url, member_id, color) VALUES (?, 'url', ?, ?, ?)",
                (name, url, member_id, color),
            )
        store.save_events(conn(), cur.lastrowid, events)
        return jsonify(calendar_json(cur.lastrowid)), 201

    @app.post("/api/calendars/upload")
    def upload_calendar():
        f = request.files.get("file")
        if f is None:
            raise BadRequest("Välj en .ics-fil.")
        raw = f.read()
        events = ical_sources.parse_events(raw)
        name = (
            _text(request.form.get("name"), "Namn", 100, required=False)
            or ical_sources.calendar_name(raw)
            or Path(f.filename or "Kalender").stem[:100]
        )
        member_id = _int_or_none(request.form.get("member_id"))
        color = _color(request.form.get("color"))
        with conn():
            cur = conn().execute(
                "INSERT INTO calendars (name, kind, member_id, color) VALUES (?, 'file', ?, ?)",
                (name, member_id, color),
            )
        store.save_events(conn(), cur.lastrowid, events)
        return jsonify(calendar_json(cur.lastrowid)), 201

    @app.put("/api/calendars/<int:cid>")
    def update_calendar(cid):
        current = calendar_json(cid)
        data = body()
        name = _text(data.get("name", current["name"]), "Namn", 100)
        member_id = _int_or_none(data["member_id"]) if "member_id" in data else current["member_id"]
        color = _color(data["color"]) if "color" in data else current["color"]
        url = current["url"]
        if current["kind"] == "url" and data.get("url"):
            url = ical_sources.normalize_url(_text(data["url"], "Länk", 2000))
        with conn():
            conn().execute(
                "UPDATE calendars SET name = ?, member_id = ?, color = ?, url = ? WHERE id = ?",
                (name, member_id, color, url, cid),
            )
        if url != current["url"]:
            store.refresh_calendar(conn(), cid)
        return jsonify(calendar_json(cid))

    @app.delete("/api/calendars/<int:cid>")
    def delete_calendar(cid):
        with conn():
            conn().execute("DELETE FROM calendars WHERE id = ?", (cid,))
        return "", 204

    @app.post("/api/calendars/<int:cid>/refresh")
    def refresh_calendar(cid):
        calendar_json(cid)
        store.refresh_calendar(conn(), cid)
        return jsonify(calendar_json(cid))

    @app.post("/api/calendars/refresh")
    def refresh_all():
        errors = {}
        for (cid,) in conn().execute("SELECT id FROM calendars WHERE kind = 'url'").fetchall():
            try:
                store.refresh_calendar(conn(), cid)
            except ical_sources.CalendarError as exc:
                errors[cid] = str(exc)
        return jsonify(errors=errors)

    # ------------------------------------------------------------ arbetspass

    @app.get("/api/shift-types")
    def list_shift_types():
        return jsonify(db.rows(conn().execute("SELECT * FROM shift_types ORDER BY member_id, start_time, id")))

    def shift_type_fields(data: dict, current: dict | None = None) -> tuple:
        current = current or {}
        name = _text(data.get("name", current.get("name")), "Namn", 40)
        short = _text(data.get("short", current.get("short")), "Kortnamn", 4, required=False) or name[:2]
        start_time = _time(data.get("start_time", current.get("start_time")))
        end_time = _time(data.get("end_time", current.get("end_time")))
        if bool(start_time) != bool(end_time):
            raise BadRequest("Ange både start- och sluttid, eller ingen (heldag).")
        color = _color(data.get("color"), current.get("color") or "#0d9488")
        return name, short, start_time, end_time, color

    @app.post("/api/shift-types")
    def add_shift_type():
        data = body()
        member_id = _int_or_none(data.get("member_id"))
        one("SELECT id FROM members WHERE id = ?", member_id)
        fields = shift_type_fields(data)
        with conn():
            cur = conn().execute(
                "INSERT INTO shift_types (member_id, name, short, start_time, end_time, color)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (member_id, *fields),
            )
        return jsonify(one("SELECT * FROM shift_types WHERE id = ?", cur.lastrowid)), 201

    @app.put("/api/shift-types/<int:tid>")
    def update_shift_type(tid):
        current = one("SELECT * FROM shift_types WHERE id = ?", tid)
        fields = shift_type_fields(body(), current)
        with conn():
            conn().execute(
                "UPDATE shift_types SET name = ?, short = ?, start_time = ?, end_time = ?, color = ? WHERE id = ?",
                (*fields, tid),
            )
        return jsonify(one("SELECT * FROM shift_types WHERE id = ?", tid))

    @app.delete("/api/shift-types/<int:tid>")
    def delete_shift_type(tid):
        with conn():
            conn().execute("DELETE FROM shift_types WHERE id = ?", (tid,))
        return "", 204

    @app.get("/api/shifts")
    def list_shifts():
        member_id = _int_or_none(request.args.get("member_id"))
        start = _date(request.args.get("start"), "start")
        end = _date(request.args.get("end"), "end")
        return jsonify(db.rows(conn().execute(
            "SELECT * FROM shifts WHERE member_id = ? AND date >= ? AND date < ? ORDER BY date",
            (member_id, start, end),
        )))

    @app.put("/api/shifts")
    def put_shift():
        data = body()
        member_id = _int_or_none(data.get("member_id"))
        one("SELECT id FROM members WHERE id = ?", member_id)
        day = _date(data.get("date"))
        type_id = _int_or_none(data.get("shift_type_id"))
        if type_id is not None:
            st = one("SELECT member_id FROM shift_types WHERE id = ?", type_id)
            if st["member_id"] != member_id:
                raise BadRequest("Passtypen hör till en annan person.")
        note = _text(data.get("note"), "Anteckning", 300, required=False)
        store.set_shift(conn(), member_id, day, type_id, note)
        return jsonify(ok=True)

    @app.post("/api/shifts/repeat")
    def repeat_shifts():
        data = body()
        member_id = _int_or_none(data.get("member_id"))
        one("SELECT id FROM members WHERE id = ?", member_id)
        try:
            weeks = int(data.get("weeks", 0))
            created = store.repeat_shifts(
                conn(), member_id, _date(data.get("start"), "Startvecka"), weeks, _date(data.get("until"), "Slutdatum")
            )
        except ValueError as exc:
            raise BadRequest(str(exc)) from None
        return jsonify(created=created)

    # ------------------------------------------------------------ händelser & export

    @app.get("/api/events")
    def list_events():
        start = _date(request.args.get("start"), "start")
        end = _date(request.args.get("end"), "end")
        if date.fromisoformat(end) - date.fromisoformat(start) > timedelta(days=400):
            raise BadRequest("För långt intervall.")
        return jsonify(store.events_between(conn(), start, end, _int_or_none(request.args.get("member_id"))))

    @app.get("/kalender.ics")
    def feed_all():
        return Response(export.build_feed(conn()), mimetype="text/calendar; charset=utf-8")

    @app.get("/kalender/<int:mid>.ics")
    def feed_member(mid):
        member = one("SELECT * FROM members WHERE id = ?", mid)
        return Response(
            export.build_feed(conn(), mid, f"{member['name']} – Familjekalender"),
            mimetype="text/calendar; charset=utf-8",
        )

    if background_refresh:
        _start_refresher(app)
    return app


def _start_refresher(app: Flask) -> None:
    """Hämtar om prenumererade kalendrar i bakgrunden när de blivit gamla."""

    def loop():
        while True:
            try:
                c = db.connect(app.config["DB_FILE"])
                try:
                    for cid in store.stale_calendars(c, app.config["REFRESH_HOURS"]):
                        try:
                            store.refresh_calendar(c, cid)
                            log.info("Uppdaterade kalender %s", cid)
                        except ical_sources.CalendarError as exc:
                            log.warning("Kalender %s: %s", cid, exc)
                finally:
                    c.close()
            except Exception:  # noqa: BLE001 - tråden får aldrig dö
                log.exception("Fel vid bakgrundsuppdatering")
            time.sleep(600)

    threading.Thread(target=loop, name="kalender-uppdatering", daemon=True).start()
