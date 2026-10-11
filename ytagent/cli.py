"""Command line: python -m ytagent <command>"""
from __future__ import annotations

import argparse
import logging
import sys

from . import history, youtube
from .config import Settings, load_settings


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


def cmd_auth(settings: Settings, args) -> int:
    youtube.get_credentials(settings, interactive=True)
    channel = youtube.youtube_client(settings).channels().list(part="snippet", mine=True).execute()
    names = [c["snippet"]["title"] for c in channel.get("items", [])]
    print(f"Inloggad. Kanal: {', '.join(names) or '(ingen kanal hittad)'}")
    return 0


def cmd_run(settings: Settings, args) -> int:
    from .pipeline import Pipeline

    result = Pipeline(settings).run(count=args.count, task=args.task or "", upload=not args.no_upload)
    print(f"\nKlart: {len(result.succeeded)} lyckades, {len(result.failed)} misslyckades")
    for e in result.succeeded:
        yt = f"  https://studio.youtube.com/video/{e['youtube_id']}/edit" if e.get("youtube_id") else ""
        print(f"  [{e['status']}] {e['title']}\n    {e['video']}{yt}")
    for f in result.failed:
        print(f"  [FEL] {f['idea']}: {f['error']}")
    return 0 if not result.failed else 1


def cmd_approve(settings: Settings, args) -> int:
    youtube.set_visibility(settings, args.video_id, publish_at=args.at)
    for item in history.load(settings.history_path):
        if item.get("youtube_id") == args.video_id:
            item["status"] = "scheduled" if args.at else "published"
            item["publish_at"] = args.at
            history.upsert(settings.history_path, item)
    print("Schemalagd" if args.at else "Publicerad", args.video_id)
    return 0


def cmd_list(settings: Settings, args) -> int:
    for item in history.load(settings.history_path):
        print(f"{item.get('status', '?'):18} {item.get('youtube_id', '-'):12} {item.get('title', item['id'])}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ytagent", description="Automatisk YouTube Shorts-agent")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("auth", help="Logga in på YouTube (öppnar webbläsaren)")

    run = sub.add_parser("run", help="Skapa videos enligt brief.md")
    run.add_argument("--count", type=int, help="Antal videos (annars från brief.md)")
    run.add_argument("--task", help='Extra uppdrag, t.ex. "3 videos om havets djup"')
    run.add_argument("--no-upload", action="store_true", help="Rendera bara, ladda inte upp")

    approve = sub.add_parser("approve", help="Godkänn en video: publicera nu eller schemalägg")
    approve.add_argument("video_id")
    approve.add_argument("--at", help="Schemalägg, ISO 8601 UTC, t.ex. 2026-10-12T16:00:00Z")

    sub.add_parser("list", help="Visa alla videos agenten gjort")

    args = parser.parse_args(argv)
    settings = load_settings()
    setup_logging(settings, args.verbose)
    handlers = {"auth": cmd_auth, "run": cmd_run, "approve": cmd_approve, "list": cmd_list}
    try:
        return handlers[args.command](settings, args)
    except Exception as e:
        logging.getLogger("ytagent").error("%s", e, exc_info=args.verbose)
        print(f"Fel: {e}", file=sys.stderr)
        return 1
