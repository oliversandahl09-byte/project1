"""Command line: python -m fyndagent <command>"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone

from ytagent.cli import setup_logging

from . import watches
from .config import FyndSettings, load_fynd_settings
from .models import PLATFORMS, SearchPlan
from .report import print_result, write_report
from .search import run_search

log = logging.getLogger("fyndagent")
MAX_SEEN = 3000


def _claude(settings: FyndSettings, args):
    if args.no_ai:
        return None
    from ytagent.llm import Claude
    return Claude(settings.base)


def _platforms(value: str | None) -> list[str] | None:
    if not value:
        return None
    names = [p.strip().lower() for p in value.split(",") if p.strip()]
    bad = [p for p in names if p not in PLATFORMS]
    if bad:
        raise ValueError(f"Okänd sida: {', '.join(bad)} (välj bland {', '.join(PLATFORMS)})")
    return names


def cmd_search(settings: FyndSettings, args) -> int:
    request = " ".join(args.request)
    if args.no_images:
        settings.use_images = False
    result = run_search(settings, request, claude=_claude(settings, args), limit=args.limit,
                        platforms=_platforms(args.platforms), max_price=args.max_price or 0)
    print_result(result, settings.currency)
    path = write_report(settings, request, result)
    print(f"\nRapport med bilder: {path}")
    if args.watch:
        w = watches.add(settings, request, result.plan, result.considered)
        print(f"Sparad som bevakning #{w['id']}. Kör `python -m fyndagent check` för att se nya annonser.")
    return 0 if result.matches or not result.errors else 1


def cmd_check(settings: FyndSettings, args) -> int:
    all_watches = watches.load(settings)
    chosen = [w for w in all_watches if not args.ids or w["id"] in args.ids]
    if not chosen:
        print("Inga bevakningar. Lägg till med: python -m fyndagent search \"...\" --watch")
        return 0
    claude = _claude(settings, args)
    if args.no_images:
        settings.use_images = False
    new_total = 0
    for w in chosen:
        result = run_search(settings, w["request"], claude=claude, plan=SearchPlan(**w["plan"]),
                            limit=args.limit, skip=set(w["seen"]))
        w["seen"] = (w["seen"] + result.considered)[-MAX_SEEN:]
        w["last_run"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        new_total += len(result.matches)
        if result.matches or result.errors:
            print_result(result, settings.currency, title=f"#{w['id']} {w['request']}: {len(result.matches)} nya")
            if result.matches:
                print(f"\nRapport: {write_report(settings, w['request'], result)}")
        else:
            print(f"#{w['id']} {w['request']}: inget nytt")
    watches.save(settings, all_watches)
    print(f"\n{new_total} nya träffar totalt.")
    return 0


def cmd_watches(settings: FyndSettings, args) -> int:
    items = watches.load(settings)
    if not items:
        print("Inga bevakningar.")
    for w in items:
        last = w["last_run"][:16].replace("T", " ") or "aldrig"
        print(f"#{w['id']}  {w['request']}\n     sökord: {'; '.join(w['plan']['queries'])} · senast kollad: {last}")
    return 0


def cmd_unwatch(settings: FyndSettings, args) -> int:
    ok = watches.remove(settings, args.id)
    print(f"Bevakning #{args.id} borttagen." if ok else f"Hittade ingen bevakning #{args.id}.")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fyndagent", description="Letar kläder på Vinted, Depop och Grailed")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("--limit", type=int, default=10, help="Max antal träffar att visa (standard 10)")
        p.add_argument("--no-images", action="store_true", help="Låt inte Claude titta på bilderna (billigare)")
        p.add_argument("--no-ai", action="store_true", help="Sök utan Claude: bara sökordet, ingen ranking")

    search = sub.add_parser("search", help='Sök, t.ex.: search "svart Carhartt Detroit-jacka stl M under 900 kr"')
    search.add_argument("request", nargs="+", help="Vad du letar efter, med egna ord")
    search.add_argument("--platforms", help="T.ex. vinted,grailed (standard: alla)")
    search.add_argument("--max-price", type=float, help="Maxpris i din valuta (går före det du skrev)")
    search.add_argument("--watch", action="store_true", help="Spara som bevakning")
    common(search)

    check = sub.add_parser("check", help="Kör bevakningarna och visa bara nya annonser")
    check.add_argument("ids", nargs="*", type=int, help="Bevaknings-id (tomt = alla)")
    common(check)

    sub.add_parser("watches", help="Visa bevakningar")
    unwatch = sub.add_parser("unwatch", help="Ta bort en bevakning")
    unwatch.add_argument("id", type=int)

    args = parser.parse_args(argv)
    settings = load_fynd_settings()
    setup_logging(settings.base, args.verbose)
    handlers = {"search": cmd_search, "check": cmd_check, "watches": cmd_watches, "unwatch": cmd_unwatch}
    try:
        return handlers[args.command](settings, args)
    except Exception as e:
        log.error("%s", e, exc_info=args.verbose)
        print(f"Fel: {e}", file=sys.stderr)
        return 1
