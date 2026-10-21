"""Marketplace search. None of these sites has an official public search API, so this uses the same
JSON endpoints their own websites call. They can change without notice: each source fails on its own
and never stops the others. Keep the request rate low (personal use only).
"""
from __future__ import annotations

import logging
import re
import time

import requests

from .config import FyndSettings
from .models import Listing

log = logging.getLogger(__name__)

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/130.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8",
}


class SourceError(RuntimeError):
    pass


def _num(value) -> float:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


class Source:
    name = "source"
    delay = 1.0  # seconds between requests to the same site

    def __init__(self, settings: FyndSettings):
        self.settings = settings
        self.session = requests.Session()
        self.session.headers.update(BROWSER_HEADERS)
        self._last = 0.0

    def _wait(self) -> None:
        pause = self.delay - (time.monotonic() - self._last)
        if pause > 0:
            time.sleep(pause)
        self._last = time.monotonic()

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        self._wait()
        r = self.session.request(method, url, timeout=20, **kwargs)
        if r.status_code in (401, 403):
            raise SourceError(f"{self.name} nekade sökningen (HTTP {r.status_code}), sidan kan ha bytt skydd eller API")
        if r.status_code == 429:
            raise SourceError(f"{self.name}: för många sökningar, vänta en stund")
        r.raise_for_status()
        return r

    def search(self, query: str, max_price: float = 0, limit: int = 40) -> list[Listing]:
        raise NotImplementedError


class Vinted(Source):
    name = "Vinted"

    def __init__(self, settings: FyndSettings):
        super().__init__(settings)
        self.base = f"https://{settings.vinted_domain}"
        self._has_cookie = False

    def _ensure_cookie(self) -> None:
        # The API wants the anonymous session cookie the homepage sets.
        if not self._has_cookie:
            self._request("GET", self.base + "/", headers={"Accept": "text/html"})
            self._has_cookie = True

    def search(self, query: str, max_price: float = 0, limit: int = 40) -> list[Listing]:
        self._ensure_cookie()
        params = {"search_text": query, "per_page": min(limit, 96), "page": 1, "order": "relevance"}
        if max_price:
            params["price_to"] = int(max_price)
            params["currency"] = self.settings.currency
        data = self._request("GET", self.base + "/api/v2/catalog/items", params=params).json()
        return [self.parse(item) for item in data.get("items", [])][:limit]

    def parse(self, item: dict) -> Listing:
        price = item.get("price")
        if isinstance(price, dict):  # newer shape: {"amount": "250.0", "currency_code": "SEK"}
            amount, currency = _num(price.get("amount")), price.get("currency_code", "")
        else:
            amount, currency = _num(price), item.get("currency", "")
        photo = item.get("photo") or {}
        url = item.get("url") or f"{self.base}/items/{item.get('id')}"
        return Listing(
            platform="vinted", id=str(item.get("id")), title=item.get("title", ""), price=amount,
            currency=currency or self.settings.currency, url=url if url.startswith("http") else self.base + url,
            image_url=photo.get("url", "") or (photo.get("full_size_url") or ""),
            brand=item.get("brand_title", ""), size=item.get("size_title", ""), condition=item.get("status", ""),
            seller=(item.get("user") or {}).get("login", ""),
        )


class Depop(Source):
    name = "Depop"
    API = "https://webapi.depop.com/api/v3/search/products/"

    def search(self, query: str, max_price: float = 0, limit: int = 40) -> list[Listing]:
        params = {"what": query, "items_per_page": min(limit, 48), "country": self.settings.depop_country,
                  "currency": self.settings.currency}
        if max_price:
            params["price_max"] = int(max_price)
        headers = {"Origin": "https://www.depop.com", "Referer": "https://www.depop.com/"}
        data = self._request("GET", self.API, params=params, headers=headers).json()
        return [self.parse(p) for p in data.get("products", [])][:limit]

    def parse(self, p: dict) -> Listing:
        # Handles both the v3 shape (pricing/pictures) and the older v2 shape (price/preview).
        pricing = p.get("pricing") or {}
        if pricing:
            breakdown = (pricing.get("discounted_price") or pricing.get("original_price") or {})
            amount = _num(((breakdown.get("price_breakdown") or {}).get("price") or {}).get("amount"))
            currency = pricing.get("currency_name", "")
        else:
            price = p.get("price") or {}
            amount = _num(price.get("discountedPriceAmount") or price.get("priceAmount"))
            currency = price.get("currencyName", "")
        image = ""
        pictures = p.get("pictures") or []
        if pictures and isinstance(pictures[0], dict):
            formats = pictures[0].get("formats") or {}
            image = (formats.get("P0") or formats.get("P1") or next(iter(formats.values()), {})).get("url", "")
        if not image:
            preview = p.get("preview") or {}
            image = preview.get("640") or preview.get("480") or next(iter(preview.values()), "")
        sizes = p.get("sizes") or []
        slug = p.get("slug", "")
        return Listing(
            platform="depop", id=str(p.get("id") or slug), title=p.get("description") or slug.replace("-", " "),
            price=amount, currency=currency or self.settings.currency,
            url=f"https://www.depop.com/products/{slug}/", image_url=image,
            brand=p.get("brand_name") or p.get("brandName") or "",
            size=", ".join(s if isinstance(s, str) else s.get("name", "") for s in sizes),
            condition=p.get("condition", ""),
            seller=p.get("seller_username") or "",
        )


class Grailed(Source):
    """Grailed's site searches through Algolia with a public, search-only key."""
    name = "Grailed"
    FALLBACK_KEY = "bc9ee1c014521ccf312525a4ef324a16"
    INDEX = "Listing_production"

    def __init__(self, settings: FyndSettings):
        super().__init__(settings)
        self._key = settings.grailed_api_key

    def _api_key(self) -> str:
        if not self._key:
            try:
                html = self._request("GET", "https://www.grailed.com/", headers={"Accept": "text/html"}).text
                m = re.search(r'algolia[^{}]{0,200}?[Aa]pi_?[Kk]ey["\']?\s*[:=]\s*["\']([0-9a-f]{32})', html)
                self._key = m.group(1) if m else self.FALLBACK_KEY
            except (requests.RequestException, SourceError):
                self._key = self.FALLBACK_KEY
        return self._key

    def search(self, query: str, max_price: float = 0, limit: int = 40) -> list[Listing]:
        url = f"https://{self.settings.grailed_app_id.lower()}-dsn.algolia.net/1/indexes/{self.INDEX}/query"
        headers = {"X-Algolia-Application-Id": self.settings.grailed_app_id, "X-Algolia-API-Key": self._api_key(),
                   "Content-Type": "application/json", "Origin": "https://www.grailed.com"}
        body = {"query": query, "hitsPerPage": min(limit, 60)}
        try:
            data = self._request("POST", url, json=body, headers=headers).json()
        except SourceError as e:
            raise SourceError(f"{e}. Grailed-nyckeln kan ha bytts: sätt GRAILED_ALGOLIA_KEY i .env (se README)") from e
        # Prices are USD here; the price filter runs after conversion in search.py.
        return [self.parse(h) for h in data.get("hits", [])][:limit]

    def parse(self, h: dict) -> Listing:
        designers = h.get("designers") or []
        brand = h.get("designer_names") or ", ".join(d.get("name", "") for d in designers if isinstance(d, dict))
        photo = h.get("cover_photo") or {}
        return Listing(
            platform="grailed", id=str(h.get("id")), title=h.get("title", ""), price=_num(h.get("price")),
            currency="USD", url=f"https://www.grailed.com/listings/{h.get('id')}",
            image_url=photo.get("url", "") if isinstance(photo, dict) else "",
            brand=brand, size=str(h.get("size", "")), condition=str(h.get("condition", "")).replace("is_", "").replace("_", " "),
            seller=(h.get("user") or {}).get("username", ""), description=(h.get("description") or "")[:300],
        )


SOURCES = {"vinted": Vinted, "depop": Depop, "grailed": Grailed}
