"""The agent loop: interpret the request -> search every marketplace -> filter -> let Claude rank."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from itertools import zip_longest

import anthropic

from .config import FyndSettings
from .models import PLATFORMS, Listing, Ranking, SearchPlan
from .sources import SOURCES, Source

log = logging.getLogger(__name__)

SYSTEM = (
    "You are a sharp second-hand fashion buyer who knows brands, models, sizing and how to spot fakes. "
    "You help one person find clothes on Vinted, Depop and Grailed. Be strict about hard requirements "
    "(size, price, model) and honest about doubts. Write user-facing text in Swedish."
)
MAX_CANDIDATES = 60
MAX_IMAGES = 20


@dataclass
class SearchResult:
    plan: SearchPlan
    matches: list[Listing]
    searched: int = 0
    considered: list[str] = field(default_factory=list)  # keys of listings that were judged
    errors: dict[str, str] = field(default_factory=dict)


def plan_search(claude, request: str, currency: str) -> SearchPlan:
    return claude.structured(
        SYSTEM,
        f"The user's currency is {currency}. They wrote (probably Swedish):\n<request>{request}</request>\n\n"
        "Turn this into a search plan. Queries should be what a seller would write in a listing title.",
        SearchPlan,
    )


def literal_plan(request: str) -> SearchPlan:
    return SearchPlan(summary=request, queries=[request], max_price=0, min_price=0, sizes=[], brands=[],
                      must_have=[], nice_to_have=[], avoid=[], platforms=[])


def gather(settings: FyndSettings, plan: SearchPlan, sources: dict[str, Source] | None = None,
           per_query: int = 40) -> tuple[list[Listing], dict[str, str]]:
    wanted = [p for p in (plan.platforms or PLATFORMS) if p in SOURCES]
    sources = sources if sources is not None else {p: SOURCES[p](settings) for p in wanted}
    per_platform: dict[str, list[Listing]] = {}
    errors: dict[str, str] = {}
    for name in wanted:
        source = sources.get(name)
        if source is None:
            continue
        found: list[Listing] = []
        for query in plan.queries[:3]:
            try:
                found += source.search(query, max_price=plan.max_price, limit=per_query)
            except Exception as e:  # one broken site must not stop the others
                log.warning("%s: %s", source.name, e)
                errors[name] = str(e)
                break
        per_platform[name] = found
    # Interleave platforms so every site gets a fair share of the candidate list.
    merged = [l for group in zip_longest(*per_platform.values()) for l in group if l is not None]
    return merged, errors


def prefilter(settings: FyndSettings, plan: SearchPlan, listings: list[Listing], skip: set[str] = frozenset()) -> list[Listing]:
    seen: set[str] = set()
    kept = []
    for l in listings:
        if l.key in seen or l.key in skip:
            continue
        seen.add(l.key)
        l.price_local = settings.to_local(l.price, l.currency)
        if plan.max_price and l.price_local > plan.max_price:
            continue
        if plan.min_price and l.price_local < plan.min_price:
            continue
        kept.append(l)
    return kept


def _candidate_line(i: int, l: Listing, currency: str) -> str:
    parts = [f"[{i}] {l.platform}", l.title, f"märke: {l.brand}" if l.brand else "",
             f"storlek: {l.size}" if l.size else "", f"skick: {l.condition}" if l.condition else "",
             f"{l.price_local:.0f} {currency}" + (f" ({l.price:.0f} {l.currency})" if l.currency != currency else ""),
             l.description.replace("\n", " ") if l.description else ""]
    return " | ".join(p for p in parts if p)


def rank(claude, settings: FyndSettings, request: str, plan: SearchPlan, candidates: list[Listing],
         limit: int) -> list[Listing]:
    candidates = candidates[:MAX_CANDIDATES]
    if not candidates:
        return []
    lines = "\n".join(_candidate_line(i, l, settings.currency) for i, l in enumerate(candidates))
    prompt = (f"<request>{request}</request>\n\n<plan>\n{plan.model_dump_json(indent=2)}\n</plan>\n\n"
              f"<candidates>\n{lines}\n</candidates>\n\n"
              "Score every candidate against the request. Hard requirements (size, model, must_have, avoid) "
              "that clearly fail mean a score under 5. If the size is missing, say so in the reason. "
              f"Return at most {limit} verdicts.")
    images: list[dict] = []
    if settings.use_images:
        for i, l in enumerate(candidates):
            if l.image_url and len(images) < MAX_IMAGES * 2:
                images += [{"type": "text", "text": f"Bild för kandidat [{i}]:"},
                           {"type": "image", "source": {"type": "url", "url": l.image_url}}]
    try:
        ranking = claude.structured(SYSTEM, prompt, Ranking, content_before=images or None)
    except anthropic.BadRequestError as e:  # usually an image URL the API could not fetch
        if not images:
            raise
        log.info("Bilderna gick inte att hämta (%s), rankar på text", e)
        ranking = claude.structured(SYSTEM, prompt, Ranking)
    out, used = [], set()
    for v in sorted(ranking.verdicts, key=lambda v: -v.score):
        if 0 <= v.index < len(candidates) and v.score >= 5 and v.index not in used:
            used.add(v.index)
            l = candidates[v.index]
            l.score, l.reason = v.score, v.reason
            out.append(l)
    return out[:limit]


def run_search(settings: FyndSettings, request: str, claude=None, plan: SearchPlan | None = None,
               sources: dict[str, Source] | None = None, limit: int = 10, skip: set[str] = frozenset(),
               platforms: list[str] | None = None, max_price: float = 0) -> SearchResult:
    if plan is None:
        plan = plan_search(claude, request, settings.currency) if claude else literal_plan(request)
    if platforms:
        plan.platforms = platforms
    if max_price:
        plan.max_price = max_price
    log.info("Söker: %s | %s", plan.summary, "; ".join(plan.queries))
    found, errors = gather(settings, plan, sources)
    candidates = prefilter(settings, plan, found, skip)
    log.info("%d annonser hittade, %d kvar efter pris/dubbletter", len(found), len(candidates))
    if claude:
        candidates = candidates[:MAX_CANDIDATES]
        matches = rank(claude, settings, request, plan, candidates, limit)
    else:
        candidates = matches = candidates[:limit]
    return SearchResult(plan=plan, matches=matches, searched=len(found), errors=errors,
                        considered=[l.key for l in candidates])
