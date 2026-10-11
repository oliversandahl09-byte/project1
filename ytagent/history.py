"""data/history.json: everything the agent has made, so it never repeats itself."""
from __future__ import annotations

import json
import re
from pathlib import Path


def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, items: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def upsert(path: Path, entry: dict) -> None:
    items = load(path)
    items = [i for i in items if i.get("id") != entry["id"]]
    items.append(entry)
    save(path, items)


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-zåäö']+", text.lower()) if len(w) > 3}


def max_similarity(script_text: str, items: list[dict]) -> float:
    """Word-overlap (Jaccard) against earlier scripts; guards against repetitive content."""
    mine = _words(script_text)
    best = 0.0
    for item in items:
        other = _words(item.get("script", ""))
        if mine and other:
            best = max(best, len(mine & other) / len(mine | other))
    return best
