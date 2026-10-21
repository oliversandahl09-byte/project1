import io
from types import SimpleNamespace

import pytest

from kladagent import platforms
from kladagent.agent import AgentError, ClothesAgent
from kladagent.app import create_app
from kladagent.config import Settings
from kladagent.models import Image, SearchRequest


def block(type_, **fields):
    data = {"type": type_, **fields}
    return SimpleNamespace(**data, model_dump=lambda: data)


def response(content, stop_reason):
    return SimpleNamespace(content=content, stop_reason=stop_reason, stop_details=None, usage=None)


def search_results(*urls):
    return block("web_search_tool_result",
                 content=[{"type": "web_search_result", "url": u, "title": "x"} for u in urls])


def report(listings, queries=("carhartt detroit jacket",)):
    return block("tool_use", name="report_results", input={
        "style_summary": "Workwear-jacka i brunt.",
        "message": "Här är det jag hittade.",
        "queries": list(queries),
        "listings": listings,
    })


def listing(platform, url, score=8, **extra):
    return {"platform": platform, "title": f"Jacka {score}", "url": url, "price": "500 kr", "size": "M",
            "brand": "Carhartt", "condition": "Bra", "image_url": None, "why": "Matchar.",
            "match_score": score, **extra}


class FakeClient:
    """Stands in for anthropic.Anthropic: returns the queued responses, records the requests."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self.stream))

    def stream(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        resp = self.responses.pop(0)

        class Ctx:
            def __enter__(self):
                return SimpleNamespace(get_final_message=lambda: resp)

            def __exit__(self, *a):
                return False

        return Ctx()


def make_agent(responses):
    agent = ClothesAgent(Settings(anthropic_api_key="test"))
    agent.client = FakeClient(responses)
    return agent


def test_keeps_only_listings_the_agent_actually_saw():
    seen = "https://www.vinted.se/items/111-carhartt-jacka"
    agent = make_agent([response([
        search_results(seen + "?referrer=catalog", "https://www.depop.com/products/abc-jacket/"),
        report([
            listing("vinted", seen, score=6),
            listing("depop", "https://www.depop.com/products/abc-jacket", score=9),
            listing("vinted", "https://www.vinted.se/items/999-invented"),        # never seen
            listing("grailed", "https://www.depop.com/products/abc-jacket"),      # wrong platform
            listing("vinted", seen + "/", score=5),                               # duplicate
            listing("depop", "https://evil.example.com/products/x"),              # other site
        ]),
    ], "tool_use")])

    result = agent.search(SearchRequest(text="brun carhartt jacka", max_price=900))

    assert [l.url for l in result.listings] == ["https://www.depop.com/products/abc-jacket", seen]
    assert {l.platform for l in result.search_links} == {"vinted", "depop", "grailed"}
    vinted_link = next(l for l in result.search_links if l.platform == "vinted")
    assert vinted_link.url == ("https://www.vinted.se/catalog?search_text=carhartt+detroit+jacket"
                               "&order=relevance&price_to=900")


def test_resumes_after_pause_turn_and_restricts_domains():
    url = "https://www.grailed.com/listings/123-jacket"
    paused = [block("server_tool_use", name="web_search"), search_results(url)]
    agent = make_agent([response(paused, "pause_turn"), response([report([listing("grailed", url)])], "tool_use")])

    result = agent.search(SearchRequest(text="jacka", platforms=["grailed"],
                                        images=[Image("image/png", b"png-bytes")]))

    assert [l.url for l in result.listings] == [url]
    calls = agent.client.calls
    assert len(calls) == 2
    assert calls[1]["messages"][-1] == {"role": "assistant", "content": paused}
    search_tool = next(t for t in calls[0]["tools"] if t.get("name") == "web_search")
    assert search_tool["allowed_domains"] == ["grailed.com"]
    first = calls[0]["messages"][0]["content"]
    assert first[0]["type"] == "image" and "grailed.com" in first[-1]["text"]


def test_nudges_once_then_gives_up():
    agent = make_agent([response([block("text", text="Klar!")], "end_turn")] * 2)
    with pytest.raises(AgentError):
        agent.search(SearchRequest(text="jacka"))
    assert "report_results" in agent.client.calls[1]["messages"][-1]["content"]


def test_search_urls():
    assert platforms.search_url("depop", "levis 501", "vinted.se", 300) == \
        "https://www.depop.com/search/?q=levis+501&priceMax=300"
    assert platforms.search_url("grailed", "rick owens", "vinted.se") == \
        "https://www.grailed.com/shop?query=rick+owens"
    assert platforms.platform_of("https://m.vinted.se/items/1", "vinted.se") == "vinted"
    assert platforms.platform_of("https://notvinted.se/items/1", "vinted.se") is None


class StubAgent:
    def __init__(self):
        self.requests = []

    def search(self, req):
        self.requests.append(req)
        return make_agent([response([search_results(), report([])], "tool_use")]).search(req)


def test_api_parses_form_and_images():
    stub = StubAgent()
    client = create_app(Settings(anthropic_api_key="test"), agent=stub).test_client()

    res = client.post("/api/search", data={
        "text": "vintage jeans", "max_price": "400", "size": "W32", "gender": "herr",
        "platforms": ["vinted", "depop"], "history": '[{"role": "user", "text": "hej"}]',
        "images": (io.BytesIO(b"jpg"), "outfit.jpg", "image/jpeg"),
    }, content_type="multipart/form-data")

    assert res.status_code == 200, res.json
    assert res.json["style_summary"] == "Workwear-jacka i brunt."
    req = stub.requests[0]
    assert (req.max_price, req.size, req.gender, req.platforms) == (400, "W32", "herr", ["vinted", "depop"])
    assert req.images[0].media_type == "image/jpeg" and req.history == [{"role": "user", "text": "hej"}]


def test_api_rejects_empty_and_bad_files():
    client = create_app(Settings(anthropic_api_key="test"), agent=StubAgent()).test_client()
    assert client.post("/api/search", data={"text": " "}).status_code == 400
    res = client.post("/api/search", data={"images": (io.BytesIO(b"x"), "a.pdf", "application/pdf")},
                      content_type="multipart/form-data")
    assert res.status_code == 400 and "stöds" in res.json["error"]
    assert client.get("/").status_code == 200
