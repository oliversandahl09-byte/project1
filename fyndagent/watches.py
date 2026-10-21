"""Saved searches ("bevakningar"): run again later and only show listings not seen before."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from .config import FyndSettings
from .models import SearchPlan


def load(settings: FyndSettings) -> list[dict]:
    path = settings.watches_path
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def save(settings: FyndSettings, watches: list[dict]) -> None:
    settings.watches_path.parent.mkdir(parents=True, exist_ok=True)
    settings.watches_path.write_text(json.dumps(watches, ensure_ascii=False, indent=2), encoding="utf-8")


def add(settings: FyndSettings, request: str, plan: SearchPlan, seen: list[str]) -> dict:
    watches = load(settings)
    watch = {"id": max((w["id"] for w in watches), default=0) + 1, "request": request, "plan": plan.model_dump(),
             "seen": seen, "created": datetime.now(timezone.utc).isoformat(timespec="seconds"), "last_run": ""}
    watches.append(watch)
    save(settings, watches)
    return watch


def remove(settings: FyndSettings, watch_id: int) -> bool:
    watches = load(settings)
    kept = [w for w in watches if w["id"] != watch_id]
    save(settings, kept)
    return len(kept) != len(watches)
