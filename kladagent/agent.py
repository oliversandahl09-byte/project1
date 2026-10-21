"""The search agent: Claude reads your request (text and/or outfit photos), searches the
marketplaces with web search, and reports matching listings through the report_results tool."""
from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any

import anthropic
from pydantic import ValidationError

from . import platforms
from .config import Settings
from .models import Report, SearchLink, SearchRequest, SearchResult

log = logging.getLogger(__name__)

MAX_CONTINUATIONS = 6
MAX_LISTINGS = 24
_URL = re.compile(r"""https?://[^\s"'<>\\)\]]+""")

SYSTEM = """You are a personal second hand shopper. You find clothes on Vinted, Depop and Grailed \
for one person, based on what they write and/or photos of outfits they like.

How to work:
1. Work out what they want. From photos: identify each garment (type, cut/fit, colour, material, \
details, era/aesthetic, likely brands) and the overall style. From text: take exact wishes literally \
(brand, model, colour, size, budget) and fill in the rest from their taste.
2. Write the search queries the way sellers title their listings on these sites: short, concrete, \
brand + garment + key detail ("carhartt detroit jacket brown", "vintage levis 501 w32"). Mix exact \
queries with broader style queries. For Vinted, Swedish and English terms both work.
3. Search with web_search on the allowed marketplace domains. Open promising pages with web_fetch \
when you need the price, size, condition or photo. Prefer individual listing pages (Vinted /items/, \
Depop /products/, Grailed /listings/) over category pages. Skip listings that look sold.
4. When you have searched enough, call report_results exactly once. Only report URLs you actually \
saw in search or fetch results; never invent or guess a URL. It is fine to report few listings or \
none, the person also gets search links for every query.

Write style_summary, message and why in Swedish, short and friendly. In message, mention anything \
you could not find, and ask a question if the request was too vague to search well."""

REPORT_TOOL = {
    "name": "report_results",
    "description": "Report the finished search to the person. Call this exactly once, as the last step.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["style_summary", "message", "queries", "listings"],
        "properties": {
            "style_summary": {
                "type": "string",
                "description": "1-3 sentences: the style and garments you understood they want.",
            },
            "message": {"type": "string", "description": "A short note to the person."},
            "queries": {
                "type": "array",
                "items": {"type": "string"},
                "description": "3-6 search queries, best first, that they can keep browsing with.",
            },
            "listings": {
                "type": "array",
                "description": "The best matching listings, best first.",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["platform", "title", "url", "price", "size", "brand", "condition",
                                 "image_url", "why", "match_score"],
                    "properties": {
                        "platform": {"type": "string", "enum": list(platforms.PLATFORMS)},
                        "title": {"type": "string"},
                        "url": {"type": "string", "description": "Exact listing URL from the results."},
                        "price": {"type": ["string", "null"], "description": "With currency, e.g. '350 kr'."},
                        "size": {"type": ["string", "null"]},
                        "brand": {"type": ["string", "null"]},
                        "condition": {"type": ["string", "null"]},
                        "image_url": {"type": ["string", "null"], "description": "Listing photo URL if seen."},
                        "why": {"type": "string", "description": "One sentence: why it matches."},
                        "match_score": {"type": "integer", "description": "1-10, how well it matches."},
                    },
                },
            },
        },
    },
}


class AgentError(RuntimeError):
    pass


class ClothesAgent:
    def __init__(self, settings: Settings):
        if not settings.anthropic_api_key:
            raise AgentError("ANTHROPIC_API_KEY saknas i .env")
        self.settings = settings
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key, max_retries=3)

    def search(self, req: SearchRequest) -> SearchResult:
        chosen = [p for p in platforms.PLATFORMS if p in req.platforms] or list(platforms.PLATFORMS)
        domain_map = platforms.domains(self.settings.vinted_domain)
        allowed = [domain_map[p] for p in chosen]
        tools: list[dict] = [
            {"type": "web_search_20260209", "name": "web_search", "max_uses": 12, "allowed_domains": allowed},
            {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 10, "allowed_domains": allowed},
            REPORT_TOOL,
        ]
        messages: list[dict] = [{"role": "user", "content": self._user_content(req, allowed)}]
        seen: set[str] = set()
        nudged = False

        for _ in range(MAX_CONTINUATIONS):
            with self.client.beta.messages.stream(
                model=self.settings.claude_model,
                max_tokens=32000,
                system=SYSTEM,
                thinking={"type": "adaptive"},
                output_config={"effort": self.settings.effort},
                # If a request is declined by safety classifiers, the API retries it on a fallback model.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                tools=tools,
                messages=messages,
            ) as stream:
                response = stream.get_final_message()
            log.debug("Claude usage: %s", response.usage)
            seen |= _seen_urls(response.content)

            if response.stop_reason == "refusal":
                raise AgentError(f"Claude avböjde förfrågan: {response.stop_details}")
            if response.stop_reason == "max_tokens":
                raise AgentError("Svaret blev avklippt (max_tokens)")

            report = next((b for b in response.content
                           if b.type == "tool_use" and b.name == "report_results"), None)
            if report is not None:
                try:
                    parsed = Report.model_validate(report.input)
                except ValidationError as e:
                    raise AgentError(f"Ogiltigt svar från agenten: {e}") from e
                return self._finish(parsed, seen, chosen, req)

            # pause_turn: the server-side search loop hit its limit; sending the turn back resumes it.
            messages.append({"role": "assistant", "content": response.content})
            if response.stop_reason != "pause_turn":
                if nudged:
                    break
                nudged = True
                messages.append({"role": "user", "content": "Rapportera det du har hittat med report_results nu."})

        raise AgentError("Agenten blev inte klar med sökningen, försök igen")

    def _user_content(self, req: SearchRequest, allowed: list[str]) -> list[dict]:
        content: list[dict] = []
        for img in req.images:
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": img.media_type,
                           "data": base64.b64encode(img.data).decode()},
            })

        lines = []
        if req.history:
            lines.append("<earlier_in_this_chat>")
            lines += [f"{t.get('role', 'user')}: {t.get('text', '')}" for t in req.history[-10:]]
            lines.append("</earlier_in_this_chat>")
        if req.images:
            lines.append(f"I attached {len(req.images)} photo(s) of outfits/garments I like.")
        lines.append(f"My request: {req.text.strip() or '(no text, go by the photos)'}")
        filters = [f"search only these sites: {', '.join(allowed)}"]
        if req.max_price:
            filters.append(f"max price {req.max_price} {self.settings.currency}")
        if req.size:
            filters.append(f"my size: {req.size}")
        if req.gender:
            filters.append(f"department: {'womenswear' if req.gender == 'dam' else 'menswear'}")
        lines.append("Filters: " + "; ".join(filters))
        content.append({"type": "text", "text": "\n".join(lines)})
        return content

    def _finish(self, report: Report, seen: set[str], chosen: list[str], req: SearchRequest) -> SearchResult:
        vinted = self.settings.vinted_domain
        listings, used = [], set()
        for item in sorted(report.listings, key=lambda l: -l.match_score):
            key = platforms.normalize(item.url)
            # Drop anything that isn't on the platform it claims, or that the agent never actually saw.
            if platforms.platform_of(item.url, vinted) != item.platform or key not in seen or key in used:
                log.info("Skippar annons som inte gick att verifiera: %s", item.url)
                continue
            if item.image_url and not item.image_url.startswith("https://"):
                item.image_url = None
            used.add(key)
            listings.append(item)

        queries = [q.strip() for q in report.queries if q.strip()][:6] or [req.text.strip()[:80]]
        links = [SearchLink(platform=p, query=q, url=platforms.search_url(p, q, vinted, req.max_price))
                 for q in queries if q for p in chosen]
        return SearchResult(style_summary=report.style_summary, message=report.message, queries=queries,
                            listings=listings[:MAX_LISTINGS], search_links=links)


def _seen_urls(content: list[Any]) -> set[str]:
    """Normalized URLs in everything web search, web fetch (and their filtering code) returned."""
    found: set[str] = set()
    for block in content:
        if block.type.endswith("_tool_result"):
            for url in _URL.findall(json.dumps(block.model_dump(), ensure_ascii=False)):
                found.add(platforms.normalize(url))
    return found
