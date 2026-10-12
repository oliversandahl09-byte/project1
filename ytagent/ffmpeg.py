"""Small helpers for calling ffmpeg/ffprobe."""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


class FFmpegError(RuntimeError):
    pass


def require_ffmpeg() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            raise FFmpegError(
                f"{tool} hittas inte. Installera ffmpeg (Windows: winget install Gyan.FFmpeg, "
                "Mac: brew install ffmpeg) och öppna sedan ett NYTT terminalfönster."
            )


def run(args: list[str], cwd: Path | None = None) -> None:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args]
    log.debug("ffmpeg %s", " ".join(args))
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if proc.returncode != 0:
        raise FFmpegError(f"ffmpeg misslyckades: {proc.stderr.strip()[-1500:]}")


def probe_duration(path: Path) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise FFmpegError(f"ffprobe misslyckades för {path}: {proc.stderr.strip()}")
    return float(json.loads(proc.stdout)["format"]["duration"])
