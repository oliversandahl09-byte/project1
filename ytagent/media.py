"""Step 4: find licensed stock footage for each segment.

Sources (both free for commercial use, no attribution required; we credit anyway):
- Pixabay (PIXABAY_API_KEY)
- Pexels  (PEXELS_API_KEY)
Every source that has a key is tried in turn. Per segment the order of preference is:
video -> broader video search -> photo (animated with zoom) -> plain background.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import requests

from .config import Settings

log = logging.getLogger(__name__)


@dataclass
class Clip:
    path: Path | None
    kind: str  # "video" | "photo" | "none"
    credit: str = ""
    source_url: str = ""


class StockSource:
    name = ""

    def __init__(self):
        self.session = requests.Session()
        self.used_ids: set[int] = set()

    def _get(self, url: str, params: dict) -> dict:
        r = self.session.get(url, params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def _download(self, url: str, dest: Path) -> Path:
        with self.session.get(url, stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(1 << 16):
                    f.write(chunk)
        return dest

    def find_video(self, query: str, min_seconds: float, dest: Path) -> Clip | None:
        raise NotImplementedError

    def find_photo(self, query: str, dest: Path) -> Clip | None:
        raise NotImplementedError


class Pexels(StockSource):
    name = "Pexels"
    API = "https://api.pexels.com"

    def __init__(self, api_key: str):
        super().__init__()
        self.session.headers["Authorization"] = api_key

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
        data = self._get(f"{self.API}/videos/search", {"query": query, "orientation": "portrait", "per_page": 15})
        candidates = [v for v in data.get("videos", []) if v["id"] not in self.used_ids]
        # Prefer clips long enough to avoid looping; stable sort keeps relevance order.
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
        data = self._get(f"{self.API}/v1/search", {"query": query, "orientation": "portrait", "per_page": 10})
        for photo in data.get("photos", []):
            if photo["id"] in self.used_ids:
                continue
            self.used_ids.add(photo["id"])
            self._download(photo["src"].get("large2x") or photo["src"]["original"], dest)
            return Clip(dest, "photo", f"Photo by {photo['photographer']} on Pexels", photo.get("url", ""))
        return None


class Pixabay(StockSource):
    name = "Pixabay"
    API = "https://pixabay.com/api"

    def __init__(self, api_key: str):
        super().__init__()
        self.key = api_key

    @staticmethod
    def _best_file(hit: dict) -> dict | None:
        files = [f for f in (hit.get("videos") or {}).values() if f.get("url") and f.get("height")]
        sharp = [f for f in files if min(f["width"], f["height"]) >= 1080]
        if sharp:
            return min(sharp, key=lambda f: f["width"] * f["height"])
        return max(files, key=lambda f: f["height"], default=None)

    def find_video(self, query: str, min_seconds: float, dest: Path) -> Clip | None:
        data = self._get(f"{self.API}/videos/", {"key": self.key, "q": query[:100], "per_page": 20,
                                                 "safesearch": "true"})
        candidates = [h for h in data.get("hits", []) if h["id"] not in self.used_ids]
        # Prefer vertical clips (no crop needed), then long enough ones; stable sort keeps relevance.
        def is_vertical(h: dict) -> bool:
            f = self._best_file(h)
            return bool(f) and f["height"] >= f["width"]
        candidates.sort(key=lambda h: (not is_vertical(h), h.get("duration", 0) < min_seconds))
        for hit in candidates:
            f = self._best_file(hit)
            if not f:
                continue
            self.used_ids.add(hit["id"])
            self._download(f["url"], dest)
            return Clip(dest, "video", f"Video by {hit.get('user', 'unknown')} on Pixabay", hit.get("pageURL", ""))
        return None

    def find_photo(self, query: str, dest: Path) -> Clip | None:
        data = self._get(f"{self.API}/", {"key": self.key, "q": query[:100], "image_type": "photo",
                                          "orientation": "vertical", "per_page": 20, "safesearch": "true"})
        for hit in data.get("hits", []):
            if hit["id"] in self.used_ids or not hit.get("largeImageURL"):
                continue
            self.used_ids.add(hit["id"])
            self._download(hit["largeImageURL"], dest)
            return Clip(dest, "photo", f"Photo by {hit.get('user', 'unknown')} on Pixabay", hit.get("pageURL", ""))
        return None


def stock_sources(settings: Settings) -> list[StockSource]:
    sources: list[StockSource] = []
    if settings.pixabay_api_key:
        sources.append(Pixabay(settings.pixabay_api_key))
    if settings.pexels_api_key:
        sources.append(Pexels(settings.pexels_api_key))
    if not sources:
        raise RuntimeError("Ingen nyckel för stockfilm. Lägg in PIXABAY_API_KEY (eller PEXELS_API_KEY) i .env")
    return sources


def _try(source: StockSource, fn, *args) -> Clip | None:
    try:
        return fn(*args)
    except requests.RequestException as e:
        log.warning("%s-fel: %s", source.name, e)
        return None


def fetch_clips(settings: Settings, queries: list[str], durations: list[float], out_dir: Path,
                sources: list[StockSource] | None = None) -> list[Clip]:
    out_dir.mkdir(parents=True, exist_ok=True)
    sources = sources or stock_sources(settings)
    clips: list[Clip] = []
    for i, (query, seconds) in enumerate(zip(queries, durations)):
        video_dest, photo_dest = out_dir / f"clip_{i:02d}.mp4", out_dir / f"clip_{i:02d}.jpg"
        broad = query.split()[0] if query.split() else query  # the first word is usually the subject
        clip = None
        for attempt in ("video", "broad", "photo"):
            for src in sources:
                if attempt == "video":
                    clip = _try(src, src.find_video, query, seconds, video_dest)
                elif attempt == "broad":
                    clip = _try(src, src.find_video, broad, seconds, video_dest)
                else:
                    clip = _try(src, src.find_photo, query, photo_dest)
                if clip:
                    break
            if clip:
                break
        if clip is None:
            log.warning("Inget material hittades för '%s', använder bakgrund", query)
            clip = Clip(None, "none")
        clips.append(clip)
    return clips
