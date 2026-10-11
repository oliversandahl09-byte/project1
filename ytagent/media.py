"""Step 4: find licensed stock footage on Pexels for each segment.

Pexels license: free for commercial use, no attribution required (we credit anyway).
Order of preference: portrait video -> portrait photo (animated with zoom) -> plain background.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import requests

from .config import Settings

log = logging.getLogger(__name__)

API = "https://api.pexels.com"


@dataclass
class Clip:
    path: Path | None
    kind: str  # "video" | "photo" | "none"
    credit: str = ""
    source_url: str = ""


class Pexels:
    def __init__(self, settings: Settings):
        if not settings.pexels_api_key:
            raise RuntimeError("PEXELS_API_KEY saknas i .env")
        self.session = requests.Session()
        self.session.headers["Authorization"] = settings.pexels_api_key
        self.used_ids: set[int] = set()

    def _get(self, path: str, params: dict) -> dict:
        r = self.session.get(f"{API}{path}", params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def _download(self, url: str, dest: Path) -> Path:
        with self.session.get(url, stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(1 << 16):
                    f.write(chunk)
        return dest

    @staticmethod
    def _best_file(video: dict) -> dict | None:
        files = [f for f in video.get("video_files", [])
                 if f.get("file_type") == "video/mp4" and f.get("height") and f.get("width")
                 and f["height"] >= f["width"] and f["height"] >= 1280]
        if not files:
            return None
        # Closest to 1920 tall keeps downloads small but sharp.
        return min(files, key=lambda f: abs(f["height"] - 1920))

    def find_video(self, query: str, min_seconds: float, dest: Path) -> Clip | None:
        data = self._get("/videos/search", {"query": query, "orientation": "portrait", "per_page": 15})
        candidates = [v for v in data.get("videos", []) if v["id"] not in self.used_ids]
        # Prefer clips long enough to avoid looping; stable sort keeps Pexels' relevance order.
        candidates.sort(key=lambda v: v.get("duration", 0) < min_seconds)
        for video in candidates:
            f = self._best_file(video)
            if not f:
                continue
            self.used_ids.add(video["id"])
            self._download(f["link"], dest)
            return Clip(dest, "video", f"Video by {video['user']['name']} on Pexels", video.get("url", ""))
        return None

    def find_photo(self, query: str, dest: Path) -> Clip | None:
        data = self._get("/v1/search", {"query": query, "orientation": "portrait", "per_page": 10})
        for photo in data.get("photos", []):
            if photo["id"] in self.used_ids:
                continue
            self.used_ids.add(photo["id"])
            self._download(photo["src"].get("large2x") or photo["src"]["original"], dest)
            return Clip(dest, "photo", f"Photo by {photo['photographer']} on Pexels", photo.get("url", ""))
        return None


def fetch_clips(settings: Settings, queries: list[str], durations: list[float], out_dir: Path) -> list[Clip]:
    out_dir.mkdir(parents=True, exist_ok=True)
    pexels = Pexels(settings)
    clips: list[Clip] = []
    for i, (query, seconds) in enumerate(zip(queries, durations)):
        clip = None
        try:
            clip = pexels.find_video(query, seconds, out_dir / f"clip_{i:02d}.mp4")
            if clip is None:
                # Broaden the query: the first word is usually the subject.
                broad = query.split()[0]
                clip = pexels.find_video(broad, seconds, out_dir / f"clip_{i:02d}.mp4")
            if clip is None:
                clip = pexels.find_photo(query, out_dir / f"clip_{i:02d}.jpg")
        except requests.RequestException as e:
            log.warning("Pexels-fel för '%s': %s", query, e)
        if clip is None:
            log.warning("Inget material hittades för '%s', använder bakgrund", query)
            clip = Clip(None, "none")
        clips.append(clip)
    return clips
