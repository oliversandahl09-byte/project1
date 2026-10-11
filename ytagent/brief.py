"""Reads brief.md.

The brief is free markdown for Claude, plus a "## Settings" section with
`- key: value` lines that the code reads directly (count, length, etc.).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Brief:
    text: str
    settings: dict[str, str] = field(default_factory=dict)

    @property
    def video_count(self) -> int:
        return int(self.settings.get("videos_per_run", "1"))

    @property
    def target_seconds(self) -> int:
        return int(self.settings.get("target_length_seconds", "45"))

    @property
    def language(self) -> str:
        return self.settings.get("language", "English")

    @property
    def format(self) -> str:
        return self.settings.get("format", "shorts").lower()

    @property
    def category_id(self) -> str:
        # 27 = Education, 22 = People & Blogs, 28 = Science & Technology
        return self.settings.get("youtube_category_id", "27")


_SETTING_RE = re.compile(r"^\s*[-*]\s*([A-Za-z_]+)\s*:\s*(.+?)\s*$")


def parse_brief(text: str) -> Brief:
    settings: dict[str, str] = {}
    in_settings = False
    for line in text.splitlines():
        if line.startswith("#"):
            in_settings = line.lstrip("#").strip().lower() == "settings"
            continue
        if in_settings:
            m = _SETTING_RE.match(line)
            if m:
                settings[m.group(1).lower()] = m.group(2)
    return Brief(text=text, settings=settings)


def load_brief(path: Path) -> Brief:
    if not path.exists():
        raise FileNotFoundError(f"Hittar inte {path}. Kopiera brief.example.md till brief.md och fyll i.")
    return parse_brief(path.read_text(encoding="utf-8"))
