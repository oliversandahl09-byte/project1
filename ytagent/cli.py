"""Command line: python -m ytagent <command>"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import history, scheduler, youtube
from .brief import load_brief
from .config import Settings, load_settings

log = logging.getLogger("ytagent")
LEARN_INTERVAL = timedelta(days=3)


def setup_logging(settings: Settings, verbose: bool) -> None:
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    fmt = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
    file_handler = logging.FileHandler(settings.logs_dir / "agent.log", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    logging.basicConfig(level=logging.DEBUG, format=fmt, handlers=[file_handler, console])
    for noisy in ("googleapiclient", "urllib3", "httpx", "anthropic", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _local(settings: Settings, iso_utc: str | None) -> str:
    if not iso_utc:
        return ""
    tz = ZoneInfo(load_brief(settings.brief_path).timezone)
    return datetime.fromisoformat(iso_utc.replace("Z", "+00:00")).astimezone(tz).strftime("%a %d %b %H:%M")


def _print_result(result) -> None:
    print(f"\nKlart: {len(result.succeeded)} lyckades, {len(result.failed)} misslyckades")
    for e in result.succeeded:
        yt = f"\n    https://studio.youtube.com/video/{e['youtube_id']}/edit" if e.get("youtube_id") else ""
        print(f"  [{e['status']}] {e['title']}  ({e.get('niche', '')})\n    {e['video']}{yt}")
    for f in result.failed:
        print(f"  [FEL] {f['idea']}: {f['error']}")


def cmd_auth(settings: Settings, args) -> int:
    youtube.get_credentials(settings, interactive=True)
    channel = youtube.youtube_client(settings).channels().list(part="snippet", mine=True).execute()
    names = [c["snippet"]["title"] for c in channel.get("items", [])]
    print(f"Inloggad. Kanal: {', '.join(names) or '(ingen kanal hittad)'}")
    return 0


def cmd_run(settings: Settings, args) -> int:
    from .pipeline import Pipeline

    task = " ".join(args.task or [])
    result = Pipeline(settings).run(count=args.count, task=task, niche=args.niche or "", upload=not args.no_upload)
    _print_result(result)
    return 0 if not result.failed else 1


def _retry_uploads(settings: Settings, ids: list[str] | None = None) -> int:
    from .pipeline import Pipeline

    brief = load_brief(settings.brief_path)
    pipeline = Pipeline(settings)
    failures = 0
    for item in history.load(settings.history_path):
        wanted = item["id"] in ids if ids else item.get("upload_pending")
        if wanted and not item.get("youtube_id") and item.get("status") == "rendered":
            try:
                pipeline.upload(brief, item)
            except Exception as e:
                failures += 1
                log.error("Uppladdning av %s misslyckades: %s", item["id"], e)
    return failures


def cmd_upload(settings: Settings, args) -> int:
    return 1 if _retry_uploads(settings, args.ids or None) else 0


def cmd_approve(settings: Settings, args) -> int:
    brief = load_brief(settings.brief_path)
    items = history.load(settings.history_path)
    if args.now:
        publish_at = None
    else:
        publish_at = args.at or scheduler.next_slots(brief, items, 1)[0]
    youtube.set_visibility(settings, args.video_id, publish_at=publish_at)
    for item in items:
        if item.get("youtube_id") == args.video_id:
            if publish_at:
                item.update(status="scheduled", publish_at=publish_at)
            else:
                item.update(status="published", published_at=datetime.now(timezone.utc).isoformat())
            history.upsert(settings.history_path, item)
    print(f"Schemalagd till {_local(settings, publish_at)}" if publish_at else "Publicerad nu", args.video_id)
    return 0


def cmd_analyze(settings: Settings, args) -> int:
    from . import analytics, learn
    from .llm import Claude

    updated = analytics.refresh(settings)
    print(f"Statistik hämtad för {len(updated)} videos")
    text = learn.update_learnings(settings, Claude(settings), load_brief(settings.brief_path))
    print(text or f"För lite data för lärdomar ännu (minst {learn.MIN_VIDEOS_FOR_LESSONS} videos med statistik).")
    return 0


def _learnings_stale(settings: Settings) -> bool:
    path = settings.learnings_path
    if not path.exists():
        return True
    age = time.time() - path.stat().st_mtime
    return age > LEARN_INTERVAL.total_seconds()


def cmd_auto(settings: Settings, args) -> int:
    """For cron / Task Scheduler: learn from stats, retry failed uploads, fill the publishing queue."""
    from . import analytics, learn, scheduler as sched
    from .llm import Claude
    from .pipeline import Pipeline

    brief = load_brief(settings.brief_path)
    try:
        analytics.refresh(settings)
        if _learnings_stale(settings):
            learn.update_learnings(settings, Claude(settings), brief)
    except Exception as e:  # analytics must never block production
        log.warning("Analytics/inlärning hoppades över: %s", e)

    if _retry_uploads(settings):
        log.warning("Vissa uppladdningar misslyckades igen (kvot?). Försöker vid nästa körning.")

    needed = sched.videos_needed(brief, history.load(settings.history_path))
    if needed == 0:
        print("Kön är full; inga nya videos behövs just nu.")
        return 0
    count = min(needed, brief.max_videos_per_run)
    log.info("Behöver %d nya videos för att fylla %d dagar framåt", count, brief.buffer_days)
    result = Pipeline(settings).run(count=count, task=" ".join(args.task or []), niche=args.niche or "")
    _print_result(result)
    return 0 if not result.failed else 1


def cmd_schedule(settings: Settings, args) -> int:
    brief = load_brief(settings.brief_path)
    items = history.load(settings.history_path)
    print(f"Publiceringstider: {', '.join(brief.publish_times)} ({brief.timezone}), max {brief.max_per_day}/dag")
    upcoming = sorted((i for i in items if i.get("status") == "scheduled"), key=lambda i: i.get("publish_at", ""))
    for i in upcoming:
        print(f"  {_local(settings, i['publish_at'])}  {i.get('title')}")
    print("Nästa lediga tider: " + ", ".join(_local(settings, s) for s in scheduler.next_slots(brief, items, 3)))
    return 0


def cmd_list(settings: Settings, args) -> int:
    for item in history.load(settings.history_path):
        stats = item.get("stats") or {}
        extra = f"  {stats.get('views', 0)} visn, {float(stats.get('averageViewPercentage', 0) or 0):.0f}% sett" if stats else ""
        when = _local(settings, item.get("publish_at")) if item.get("publish_at") else ""
        print(f"{item.get('status', '?'):18} {item.get('youtube_id') or '-':12} {when:17} "
              f"{item.get('title', item['id'])}{extra}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ytagent", description="Automatisk YouTube Shorts-agent")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("auth", help="Logga in på YouTube (öppnar webbläsaren)")

    run = sub.add_parser("run", help='Skapa videos, t.ex.: run "gör 3 videos om rymden i mystisk stil"')
    run.add_argument("task", nargs="*", help="Fritt uppdrag (svenska eller engelska)")
    run.add_argument("--niche", help="Välj en nisch från brief.md")
    run.add_argument("--count", type=int, help="Antal videos")
    run.add_argument("--no-upload", action="store_true", help="Rendera bara, ladda inte upp")

    upload = sub.add_parser("upload", help="Ladda upp renderade videos som inte kom upp (t.ex. kvot slut)")
    upload.add_argument("ids", nargs="*", help="Mapp-id:n från `list` (tomt = alla som väntar)")

    approve = sub.add_parser("approve", help="Godkänn en video (schemaläggs på nästa lediga tid)")
    approve.add_argument("video_id")
    when = approve.add_mutually_exclusive_group()
    when.add_argument("--now", action="store_true", help="Publicera direkt")
    when.add_argument("--at", help="Egen tid, ISO 8601 UTC, t.ex. 2026-10-12T16:00:00Z")

    sub.add_parser("analyze", help="Hämta statistik, skriv learnings.md, uppdatera style_guide.md")

    auto = sub.add_parser("auto", help="Allt-i-ett för schemalagd körning (cron)")
    auto.add_argument("task", nargs="*", help="Valfritt uppdrag för nya videos")
    auto.add_argument("--niche")

    sub.add_parser("schedule", help="Visa publiceringsschema")
    sub.add_parser("list", help="Visa alla videos agenten gjort")

    args = parser.parse_args(argv)
    settings = load_settings()
    setup_logging(settings, args.verbose)
    handlers = {"auth": cmd_auth, "run": cmd_run, "upload": cmd_upload, "approve": cmd_approve,
                "analyze": cmd_analyze, "auto": cmd_auto, "schedule": cmd_schedule, "list": cmd_list}
    try:
        return handlers[args.command](settings, args)
    except Exception as e:
        log.error("%s", e, exc_info=args.verbose)
        print(f"Fel: {e}", file=sys.stderr)
        return 1
