"""Jobb: hämta, transkribera, hitta höjdpunkter, rendera. Körs i bakgrundstrådar."""
from __future__ import annotations

import json
import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Callable

from ytagent.config import Settings

from . import download, highlights, render, transcript
from .models import Clip, ClipEdit, Job, Word

log = logging.getLogger(__name__)


class Jobs:
    def __init__(self, settings: Settings, root: Path,
                 downloader: Callable[[str, Path], download.Downloaded] = download.download):
        self.settings = settings
        self.root = root
        self.downloader = downloader
        self.lock = threading.Lock()
        self.pool = ThreadPoolExecutor(max_workers=2)
        root.mkdir(parents=True, exist_ok=True)

    # --- lagring ---

    def dir(self, job_id: str) -> Path:
        return self.root / job_id

    def get(self, job_id: str) -> Job:
        path = self.dir(job_id) / "job.json"
        if not job_id.isalnum() or not path.exists():
            raise KeyError(job_id)
        return Job.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, job: Job) -> None:
        path = self.dir(job.id) / "job.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(job.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(path)

    def update(self, job_id: str, fn: Callable[[Job], None]) -> Job:
        with self.lock:
            job = self.get(job_id)
            fn(job)
            self.save(job)
            return job

    def all(self) -> list[Job]:
        jobs = []
        for p in self.root.glob("*/job.json"):
            try:
                jobs.append(Job.model_validate_json(p.read_text(encoding="utf-8")))
            except Exception:
                continue
        return sorted(jobs, key=lambda j: j.created, reverse=True)

    def words(self, job_id: str) -> list[Word]:
        path = self.dir(job_id) / "words.json"
        if not path.exists():
            return []
        return [Word(**w) for w in json.loads(path.read_text(encoding="utf-8"))]

    # --- flöde ---

    def create(self, url: str, count: int = 6, min_len: float = 15, max_len: float = 60) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], url=url.strip(), created=datetime.now().isoformat(timespec="seconds"))
        self.dir(job.id).mkdir(parents=True)
        self.save(job)
        self.pool.submit(self._process, job.id, count, min_len, max_len)
        return job

    def _set(self, job_id: str, status: str, message: str = "") -> None:
        def fn(j: Job):
            j.status, j.message = status, message
        self.update(job_id, fn)

    def _process(self, job_id: str, count: int, min_len: float, max_len: float) -> None:
        work = self.dir(job_id)
        try:
            job = self.get(job_id)
            self._set(job_id, "downloading", "Hämtar videon från YouTube…")
            dl = self.downloader(job.url, work)
            duration = dl.duration or _probe(dl.video)

            self._set(job_id, "transcribing", "Läser in vad som sägs…")
            words, source = [], "none"
            if dl.subtitles:
                words = transcript.parse_vtt(dl.subtitles.read_text(encoding="utf-8", errors="replace"))
                source = "youtube" if words else "none"
            if not words and self.settings.openai_api_key:
                try:
                    words, source = transcript.whisper(dl.video, work, self.settings.openai_api_key), "whisper"
                except Exception as e:
                    log.warning("Whisper misslyckades: %s", e)
            (work / "words.json").write_text(json.dumps([w.model_dump() for w in words]), encoding="utf-8")

            self._set(job_id, "analyzing", "Letar efter höjdpunkter…")
            found, method = highlights.find(dl.video, words, duration, dl.title, self.settings,
                                            count=count, min_len=min_len, max_len=max_len)

            def done(j: Job):
                j.title, j.duration = dl.title, duration
                j.source = dl.video.relative_to(work).as_posix()
                j.transcript_source, j.highlight_method = source, method
                j.clips = [Clip(id=f"c{i}", highlight=h,
                                edit=ClipEdit(start=h.start, end=h.end, title=h.title, caption=h.caption))
                           for i, h in enumerate(found, 1)]
                j.status = "ready"
                j.message = f"{len(found)} höjdpunkter hittade" if found else "Hittade inga höjdpunkter"
            self.update(job_id, done)
        except Exception as e:
            log.exception("Jobb %s misslyckades", job_id)
            self._set(job_id, "failed", str(e))

    def add_clip(self, job_id: str, start: float, end: float) -> Clip:
        result: list[Clip] = []

        def fn(j: Job):
            n = max((int(c.id[1:]) for c in j.clips), default=0) + 1
            h = highlights.Highlight(start=start, end=end, title="", reason="Eget klipp", score=0, caption="")
            clip = Clip(id=f"c{n}", highlight=h, edit=ClipEdit(start=start, end=end))
            j.clips.append(clip)
            result.append(clip)
        self.update(job_id, fn)
        return result[0]

    def render_clip(self, job_id: str, clip_id: str, edit: ClipEdit) -> None:
        def fn(j: Job):
            c = _clip(j, clip_id)
            c.edit, c.status, c.error = edit, "rendering", ""
        job = self.update(job_id, fn)
        self.pool.submit(self._render, job, clip_id, edit)

    def _render(self, job: Job, clip_id: str, edit: ClipEdit) -> None:
        work = self.dir(job.id)
        out = work / "clips" / f"{clip_id}.mp4"
        try:
            render.render(work / job.source, self.words(job.id), edit, out, self.settings.fonts_dir)

            def ok(j: Job):
                c = _clip(j, clip_id)
                c.status, c.file = "rendered", out.relative_to(work).as_posix()
                c.tiktok_publish_id = c.tiktok_status = ""
            self.update(job.id, ok)
        except Exception as e:
            log.exception("Rendering av %s/%s misslyckades", job.id, clip_id)

            def fail(j: Job):
                c = _clip(j, clip_id)
                c.status, c.error = "failed", str(e)
            self.update(job.id, fail)


def _clip(job: Job, clip_id: str) -> Clip:
    for c in job.clips:
        if c.id == clip_id:
            return c
    raise KeyError(clip_id)


def _probe(path: Path) -> float:
    from ytagent.ffmpeg import probe_duration
    return probe_duration(path)
