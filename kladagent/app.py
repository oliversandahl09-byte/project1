"""The website: one page where you describe or show what you want, and an API the page calls."""
from __future__ import annotations

import json
import logging

from flask import Flask, jsonify, render_template, request

from .agent import AgentError, ClothesAgent
from .config import Settings, load_settings
from .models import Image, SearchRequest

log = logging.getLogger(__name__)

MAX_IMAGES = 5
MAX_IMAGE_BYTES = 5 * 1024 * 1024
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


def create_app(settings: Settings | None = None, agent: ClothesAgent | None = None) -> Flask:
    settings = settings or load_settings()
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_IMAGES * MAX_IMAGE_BYTES + 1024 * 1024
    state = {"agent": agent}

    def get_agent() -> ClothesAgent:
        if state["agent"] is None:
            state["agent"] = ClothesAgent(settings)
        return state["agent"]

    @app.get("/")
    def index():
        return render_template("index.html", currency=settings.currency, vinted_domain=settings.vinted_domain)

    @app.post("/api/search")
    def search():
        try:
            req = parse_request(request)
        except ValueError as e:
            return jsonify(error=str(e)), 400
        if not req.text.strip() and not req.images:
            return jsonify(error="Skriv vad du letar efter eller lägg till en bild."), 400
        try:
            result = get_agent().search(req)
        except AgentError as e:
            log.warning("Sökningen misslyckades: %s", e)
            return jsonify(error=str(e)), 502
        except Exception:
            log.exception("Oväntat fel i sökningen")
            return jsonify(error="Något gick fel i agenten, försök igen."), 500
        return jsonify(result.model_dump())

    return app


def parse_request(r) -> SearchRequest:
    images = []
    for f in r.files.getlist("images")[:MAX_IMAGES]:
        data = f.read()
        if not data:
            continue
        if f.mimetype not in IMAGE_TYPES:
            raise ValueError(f"{f.filename}: bara JPG, PNG, WEBP och GIF stöds")
        if len(data) > MAX_IMAGE_BYTES:
            raise ValueError(f"{f.filename}: bilden är större än 5 MB")
        images.append(Image(media_type=f.mimetype, data=data))

    max_price = r.form.get("max_price", "").strip()
    try:
        history = json.loads(r.form.get("history") or "[]")
    except json.JSONDecodeError:
        history = []
    return SearchRequest(
        text=r.form.get("text", "")[:4000],
        images=images,
        platforms=r.form.getlist("platforms") or ["vinted", "depop", "grailed"],
        max_price=int(max_price) if max_price.isdigit() and int(max_price) > 0 else None,
        size=r.form.get("size", "").strip()[:40],
        gender=r.form.get("gender", "") if r.form.get("gender") in ("dam", "herr") else "",
        history=[h for h in history if isinstance(h, dict)] if isinstance(history, list) else [],
    )
