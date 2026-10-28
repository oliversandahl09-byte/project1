"""Webbappen: python -m clipper  →  http://localhost:8000"""
from __future__ import annotations

import argparse
import logging
import os
import threading
import webbrowser
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel

from ytagent.config import Settings, load_settings

from .jobs import Jobs, _clip
from .models import ClipEdit
from .tiktok import TikTok, TikTokError

log = logging.getLogger("clipper")
STATIC = Path(__file__).parent / "static"


class NewJob(BaseModel):
    url: str
    count: int = 6
    min_len: float = 15
    max_len: float = 60


class NewClip(BaseModel):
    start: float
    end: float


def make_tiktok(settings: Settings) -> TikTok:
    env = os.environ.get
    return TikTok(
        client_key=env("TIKTOK_CLIENT_KEY", ""),
        client_secret=env("TIKTOK_CLIENT_SECRET", ""),
        redirect_uri=env("TIKTOK_REDIRECT_URI") or "http://localhost:8000/tiktok/callback",
        token_file=settings.root / "secrets" / "tiktok_token.json",
        mode=(env("TIKTOK_MODE") or "inbox").lower(),
        privacy=env("TIKTOK_PRIVACY") or "SELF_ONLY",
    )


def create_app(settings: Settings, jobs: Jobs | None = None, tiktok: TikTok | None = None) -> FastAPI:
    jobs = jobs or Jobs(settings, settings.output_dir / "clips")
    tiktok = tiktok or make_tiktok(settings)
    app = FastAPI(title="Clipper")

    def job_or_404(job_id: str):
        try:
            return jobs.get(job_id)
        except KeyError:
            raise HTTPException(404, "Jobbet finns inte")

    @app.get("/", response_class=HTMLResponse)
    def index():
        return (STATIC / "index.html").read_text(encoding="utf-8")

    @app.get("/api/jobs")
    def list_jobs():
        return [{"id": j.id, "url": j.url, "title": j.title, "status": j.status, "created": j.created,
                 "clips": len(j.clips)} for j in jobs.all()]

    @app.post("/api/jobs")
    def new_job(body: NewJob):
        if "youtu" not in body.url:
            raise HTTPException(400, "Klistra in en YouTube-länk")
        return jobs.create(body.url, max(1, min(body.count, 15)), max(5, body.min_len), min(180, body.max_len))

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str):
        return job_or_404(job_id)

    @app.get("/api/jobs/{job_id}/text")
    def text(job_id: str, start: float, end: float):
        job_or_404(job_id)
        return {"text": " ".join(w.text for w in jobs.words(job_id) if start <= w.start < end)}

    @app.post("/api/jobs/{job_id}/clips")
    def add_clip(job_id: str, body: NewClip):
        job_or_404(job_id)
        if body.end - body.start < 1:
            raise HTTPException(400, "Klippet måste vara minst 1 sekund")
        return jobs.add_clip(job_id, body.start, body.end)

    @app.delete("/api/jobs/{job_id}/clips/{clip_id}")
    def delete_clip(job_id: str, clip_id: str):
        job_or_404(job_id)
        jobs.update(job_id, lambda j: j.clips.remove(_clip(j, clip_id)))
        return {"ok": True}

    @app.post("/api/jobs/{job_id}/clips/{clip_id}/render")
    def render_clip(job_id: str, clip_id: str, edit: ClipEdit):
        job = job_or_404(job_id)
        if job.status != "ready":
            raise HTTPException(409, "Videon är inte klar än")
        if not (0 <= edit.start < edit.end <= job.duration + 0.5):
            raise HTTPException(400, "Start/slut ligger utanför videon")
        if not 0.5 <= edit.speed <= 2:
            raise HTTPException(400, "Hastigheten måste vara mellan 0.5 och 2")
        try:
            jobs.render_clip(job_id, clip_id, edit)
        except KeyError:
            raise HTTPException(404, "Klippet finns inte")
        return {"ok": True}

    @app.get("/media/{job_id}/{path:path}")
    def media(job_id: str, path: str):
        job_or_404(job_id)
        base = jobs.dir(job_id).resolve()
        file = (base / path).resolve()
        if base not in file.parents or not file.is_file() or file.suffix.lower() not in {".mp4", ".webm", ".mkv", ".mov"}:
            raise HTTPException(404)
        return FileResponse(file, filename=file.name if path.startswith("clips/") else None)

    # --- TikTok ---

    @app.get("/api/tiktok")
    def tiktok_state():
        return {"configured": tiktok.configured, "logged_in": tiktok.logged_in(), "mode": tiktok.mode}

    @app.get("/tiktok/login")
    def tiktok_login():
        if not tiktok.configured:
            raise HTTPException(400, "TIKTOK_CLIENT_KEY och TIKTOK_CLIENT_SECRET saknas i .env")
        return RedirectResponse(tiktok.login_url())

    @app.get("/tiktok/callback")
    def tiktok_callback(code: str = "", state: str = "", error: str = "", error_description: str = ""):
        if error:
            return HTMLResponse(f"<p>TikTok-inloggningen avbröts: {error_description or error}</p><a href='/'>Tillbaka</a>")
        try:
            tiktok.finish_login(code, state)
        except TikTokError as e:
            return HTMLResponse(f"<p>{e}</p><a href='/'>Tillbaka</a>", status_code=400)
        return RedirectResponse("/")

    @app.post("/api/jobs/{job_id}/clips/{clip_id}/tiktok")
    def to_tiktok(job_id: str, clip_id: str):
        job = job_or_404(job_id)
        clip = _clip(job, clip_id)
        if clip.status not in {"rendered", "uploaded"} or not clip.file:
            raise HTTPException(409, "Rendera klippet först")
        try:
            publish_id = tiktok.upload(jobs.dir(job_id) / clip.file, clip.edit.caption)
        except TikTokError as e:
            raise HTTPException(502, str(e))

        def fn(j):
            c = _clip(j, clip_id)
            c.status, c.tiktok_publish_id, c.tiktok_status = "uploaded", publish_id, "PROCESSING_UPLOAD"
        return jobs.update(job_id, fn)

    @app.get("/api/jobs/{job_id}/clips/{clip_id}/tiktok")
    def tiktok_status(job_id: str, clip_id: str):
        clip = _clip(job_or_404(job_id), clip_id)
        if not clip.tiktok_publish_id:
            raise HTTPException(404, "Inte uppladdat")
        try:
            status = tiktok.status(clip.tiktok_publish_id)
        except TikTokError as e:
            raise HTTPException(502, str(e))

        def fn(j):
            _clip(j, clip_id).tiktok_status = status
        jobs.update(job_id, fn)
        return {"status": status}

    return app


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m clipper", description="YouTube → TikTok-klipp")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    import uvicorn

    from ytagent.ffmpeg import require_ffmpeg

    settings = load_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    require_ffmpeg()
    if not settings.anthropic_api_key:
        log.warning("ANTHROPIC_API_KEY saknas: höjdpunkter väljs bara utifrån ljudnivå")
    url = f"http://localhost:{args.port}"
    print(f"\nClipper körs på {url}  (Ctrl+C för att stänga)\n")
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(settings), host=args.host, port=args.port, log_level="warning")
    return 0
