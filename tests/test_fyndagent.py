"""Fyndagent without network: fake marketplace responses and a fake Claude."""
from __future__ import annotations

import json
from pathlib import Path

import anthropic

from fyndagent import cli, watches
from fyndagent.config import FyndSettings
from fyndagent.models import Ranking, SearchPlan, Verdict
from fyndagent.report import write_report
from fyndagent.search import prefilter, run_search
from fyndagent.sources import Depop, Grailed, Vinted
from ytagent.config import Settings

VINTED_ITEMS = {"items": [
    {"id": 1, "title": "Carhartt Detroit jacket svart", "price": {"amount": "650.0", "currency_code": "SEK"},
     "brand_title": "Carhartt", "size_title": "M", "status": "Mycket bra", "url": "https://www.vinted.se/items/1-carhartt",
     "photo": {"url": "https://img/v1.jpg"}, "user": {"login": "anna"}},
    {"id": 2, "title": "Carhartt Detroit jacket brun", "price": "1200.0", "currency": "SEK", "brand_title": "Carhartt",
     "size_title": "L", "url": "/items/2", "photo": {}, "user": {}},
]}
DEPOP_PRODUCTS = {"products": [
    {"id": 77, "slug": "seller-carhartt-detroit-black", "brand_name": "Carhartt", "sizes": ["M"],
     "pricing": {"currency_name": "SEK", "original_price": {"price_breakdown": {"price": {"amount": "700.00"}}}},
     "pictures": [{"formats": {"P0": {"url": "https://img/d77.jpg"}}}]},
]}
GRAILED_HITS = {"hits": [
    {"id": 555, "title": "Carhartt Detroit Jacket Blanket Lined", "price": 60, "size": "m",
     "designer_names": "Carhartt", "condition": "is_gently_used", "cover_photo": {"url": "https://img/g.jpg"},
     "user": {"username": "bob"}},
]}


def settings(tmp_path: Path) -> FyndSettings:
    return FyndSettings(base=Settings(root=tmp_path))


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload, self.status_code, self.text = payload, status, ""

    def json(self):
        return self.payload

    def raise_for_status(self):
        pass


def fake_session(source, payload, calls):
    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return FakeResponse(payload)
    source.session.request = request
    source.delay = 0
    return source


def test_vinted_parses_both_price_shapes_and_gets_cookie_first(tmp_path):
    calls = []
    v = fake_session(Vinted(settings(tmp_path)), VINTED_ITEMS, calls)
    items = v.search("carhartt detroit", max_price=900)
    assert calls[0][1] == "https://www.vinted.se/"  # cookie before API
    assert calls[1][2]["params"]["price_to"] == 900
    assert [(i.price, i.currency) for i in items] == [(650.0, "SEK"), (1200.0, "SEK")]
    assert items[1].url == "https://www.vinted.se/items/2" and items[0].image_url == "https://img/v1.jpg"


def test_depop_and_grailed_parse(tmp_path):
    d = fake_session(Depop(settings(tmp_path)), DEPOP_PRODUCTS, [])
    item = d.search("carhartt")[0]
    assert (item.price, item.size, item.image_url) == (700.0, "M", "https://img/d77.jpg")
    assert item.url == "https://www.depop.com/products/seller-carhartt-detroit-black/"

    s = settings(tmp_path)
    s.grailed_api_key = "k"
    calls = []
    g = fake_session(Grailed(s), GRAILED_HITS, calls)
    item = g.search("carhartt")[0]
    assert calls[0][2]["headers"]["X-Algolia-API-Key"] == "k"
    assert (item.currency, item.condition, item.url) == ("USD", "gently used", "https://www.grailed.com/listings/555")


class FakeSource:
    def __init__(self, listings=None, fail=False):
        self.name, self.listings, self.fail, self.queries = "fake", listings or [], fail, []

    def search(self, query, max_price=0, limit=40):
        self.queries.append(query)
        if self.fail:
            raise RuntimeError("blocked")
        return list(self.listings)


class FakeClaude:
    def __init__(self, image_error=False):
        self.calls, self.image_error = [], image_error

    def structured(self, system, prompt, schema, images=None, content_before=None):
        self.calls.append((schema, content_before))
        if schema is SearchPlan:
            return SearchPlan(summary="Svart Carhartt Detroit-jacka i M", queries=["carhartt detroit jacket"],
                              max_price=900, min_price=0, sizes=["M"], brands=["Carhartt"], must_have=["svart"],
                              nice_to_have=[], avoid=[], platforms=[])
        if schema is Ranking:
            if self.image_error and content_before:
                err = anthropic.BadRequestError.__new__(anthropic.BadRequestError)
                Exception.__init__(err, "could not fetch image")
                raise err
            assert "[0]" in prompt and "SEK" in prompt
            return Ranking(verdicts=[Verdict(index=1, score=6, reason="Rätt modell, oklar färg"),
                                     Verdict(index=0, score=9, reason="Exakt rätt"),
                                     Verdict(index=2, score=3, reason="Fel storlek"),
                                     Verdict(index=99, score=10, reason="finns inte")])
        raise AssertionError(schema)


def _sources(tmp_path, grailed_fail=False):
    s = settings(tmp_path)
    v, d, g = Vinted(s), Depop(s), Grailed(s)
    vinted = FakeSource([v.parse(i) for i in VINTED_ITEMS["items"]])
    depop = FakeSource([d.parse(p) for p in DEPOP_PRODUCTS["products"]])
    grailed = FakeSource([g.parse(h) for h in GRAILED_HITS["hits"]], fail=grailed_fail)
    return {"vinted": vinted, "depop": depop, "grailed": grailed}


def test_full_search_filters_price_ranks_and_survives_a_broken_site(tmp_path):
    s = settings(tmp_path)
    claude = FakeClaude()
    result = run_search(s, "svart carhartt detroit jacka M max 900 kr", claude=claude,
                        sources=_sources(tmp_path, grailed_fail=True))
    assert "grailed" in result.errors
    # Vinted 1200 kr is over budget; ranking keeps scores >= 5, best first, ignores bad indexes.
    assert [m.key for m in result.matches] == ["vinted:1", "depop:77"]
    assert result.matches[0].reason == "Exakt rätt"
    images = claude.calls[-1][1]
    assert {"type": "image", "source": {"type": "url", "url": "https://img/v1.jpg"}} in images

    page = write_report(s, "svart carhartt", result).read_text(encoding="utf-8")
    assert "https://www.depop.com/products/seller-carhartt-detroit-black/" in page and "9/10" in page


def test_ranking_falls_back_to_text_when_images_fail(tmp_path):
    claude = FakeClaude(image_error=True)
    result = run_search(settings(tmp_path), "carhartt", claude=claude, sources=_sources(tmp_path))
    assert result.matches and claude.calls[-1][1] is None


def test_grailed_usd_is_converted_before_price_filter(tmp_path):
    s = settings(tmp_path)
    g = Grailed(s).parse({"id": 1, "title": "x", "price": 100})
    plan = SearchPlan(summary="", queries=["x"], max_price=900, min_price=0, sizes=[], brands=[], must_have=[],
                      nice_to_have=[], avoid=[], platforms=[])
    assert prefilter(s, plan, [g]) == []  # 100 USD is about 1050 SEK
    plan.max_price = 1100
    assert prefilter(s, plan, [g])[0].price_local == 1050.0


def test_watch_only_shows_new_listings(tmp_path, monkeypatch, capsys):
    s = settings(tmp_path)
    sources = _sources(tmp_path)
    monkeypatch.setattr(cli, "load_fynd_settings", lambda: s)
    monkeypatch.setattr(cli, "_claude", lambda settings, args: None)
    monkeypatch.setattr("fyndagent.search.SOURCES", {k: (lambda _s, src=v: src) for k, v in sources.items()})

    assert cli.main(["search", "carhartt", "--watch", "--no-ai"]) == 0
    saved = watches.load(s)
    assert len(saved) == 1 and "vinted:1" in saved[0]["seen"]
    sources["vinted"].listings.append(Vinted(s).parse({"id": 3, "title": "Ny jacka", "price": "500"}))
    capsys.readouterr()
    assert cli.main(["check", "--no-ai"]) == 0
    out = capsys.readouterr().out
    assert "1 nya" in out and "Ny jacka" in out and "Detroit jacket svart" not in out
    assert json.loads(s.watches_path.read_text())[0]["last_run"]
