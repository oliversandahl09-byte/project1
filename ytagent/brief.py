"""Reads brief.md.

The brief is free markdown for Claude, plus:
- "## Niches" with up to three "### Name" subsections, each describing a niche.
- "## Settings" with `- key: value` lines that the code reads directly.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

MAX_NICHES = 3


@dataclass
class Niche:
    name: str
    description: str


@dataclass
class Brief:
    text: str
    settings: dict[str, str] = field(default_factory=dict)
    niches: list[Niche] = field(default_factory=list)

    def _int(self, key: str, default: int) -> int:
        return int(self.settings.get(key, default))

    @property
    def video_count(self) -> int:
        return self._int("videos_per_run", 1)

    @property
    def max_videos_per_run(self) -> int:
        return self._int("max_videos_per_run", 5)

    @property
    def target_seconds(self) -> int:
        return self._int("target_length_seconds", 40)

    @property
    def words_per_second(self) -> float:
        return float(self.settings.get("words_per_second", "2.5"))

    @property
    def language(self) -> str:
        return self.settings.get("language", "English")

    @property
    def language_code(self) -> str:
        return {"english": "en", "swedish": "sv", "svenska": "sv"}.get(self.language.lower(), "en")

    @property
    def format(self) -> str:
        return self.settings.get("format", "shorts").lower()

    @property
    def category_id(self) -> str:
        # 27 = Education, 22 = People & Blogs, 24 = Entertainment, 28 = Science & Technology
        return self.settings.get("youtube_category_id", "27")

    @property
    def made_for_kids(self) -> bool:
        return self.settings.get("made_for_kids", "false").lower() in {"true", "yes", "ja"}

    @property
    def timezone(self) -> str:
        return self.settings.get("timezone", "Europe/Stockholm")

    @property
    def publish_times(self) -> list[str]:
        raw = self.settings.get("publish_times", "16:00, 19:30")
        return sorted(t.strip() for t in raw.split(",") if t.strip())

    @property
    def max_per_day(self) -> int:
        return self._int("max_per_day", 1)

    @property
    def buffer_days(self) -> int:
        return self._int("buffer_days", 3)

    def find_niche(self, query: str) -> Niche | None:
        q = query.lower().strip()
        for n in self.niches:
            if q == n.name.lower() or q in n.name.lower():
                return n
        return None


_SETTING_RE = re.compile(r"^\s*[-*]\s*([A-Za-z_]+)\s*:\s*(.+?)\s*$")


def _strip_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def parse_brief(text: str) -> Brief:
    clean = _strip_comments(text)
    settings: dict[str, str] = {}
    niches: list[Niche] = []
    section = ""
    current: Niche | None = None
    for line in clean.splitlines():
        if line.startswith("## ") or line.startswith("# "):
            section = line.lstrip("#").strip().lower()
            current = None
            continue
        if line.startswith("### ") and section == "niches":
            current = Niche(line[4:].strip(), "")
            niches.append(current)
            continue
        if section == "settings":
            m = _SETTING_RE.match(line)
            if m:
                settings[m.group(1).lower()] = m.group(2)
        elif current is not None:
            current.description = (current.description + "\n" + line).strip()
    niches = [n for n in niches if n.name][:MAX_NICHES]
    return Brief(text=clean.strip(), settings=settings, niches=niches)


def load_brief(path: Path) -> Brief:
    if not path.exists():
        raise FileNotFoundError(f"Hittar inte {path}. Skapa brief.md (se README).")
    return parse_brief(path.read_text(encoding="utf-8"))
