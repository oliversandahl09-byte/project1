"""Hämtar videon och undertexter från YouTube med yt-dlp."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

SUB_LANGS = ["sv", "sv-orig", "en", "en-orig", "en-US", "en-GB"]


class DownloadError(RuntimeError):
    pass


@dataclass
class Downloaded:
    video: Path
    title: str
    duration: float
    subtitles: Path | None


def download(url: str, dest: Path, max_height: int = 1080) -> Downloaded:
    try:
        import yt_dlp
    except ImportError as e:
        raise DownloadError("yt-dlp saknas. Kör: pip install -r requirements.txt") from e

    dest.mkdir(parents=True, exist_ok=True)
    opts = {
        "outtmpl": str(dest / "source.%(ext)s"),
        "format": f"bv*[height<={max_height}][ext=mp4]+ba[ext=m4a]/b[height<={max_height}][ext=mp4]/bv*[height<={max_height}]+ba/b",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": SUB_LANGS,
        "subtitlesformat": "vtt",
        "quiet": True,
        "no_warnings": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as e:
        raise DownloadError(f"Kunde inte hämta videon: {e}") from e

    videos = [p for p in dest.glob("source.*") if p.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}]
    if not videos:
        raise DownloadError("yt-dlp hämtade ingen videofil")
    return Downloaded(
        video=videos[0],
        title=info.get("title", ""),
        duration=float(info.get("duration") or 0),
        subtitles=_best_subtitles(dest, info.get("language")),
    )


def _best_subtitles(dest: Path, video_lang: str | None) -> Path | None:
    files = {p.name.split(".")[-2]: p for p in dest.glob("source.*.vtt")}
    order = ([video_lang, f"{video_lang}-orig"] if video_lang else []) + SUB_LANGS
    for lang in order:
        if lang and lang in files:
            return files[lang]
    return next(iter(files.values()), None)
