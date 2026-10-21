"""Shows results: a short list in the terminal and an HTML page with pictures and links."""
from __future__ import annotations

import html
import json
import re
from datetime import datetime
from pathlib import Path

from .config import FyndSettings
from .search import SearchResult

PLATFORM_NAMES = {"vinted": "Vinted", "depop": "Depop", "grailed": "Grailed"}


def print_result(result: SearchResult, currency: str, title: str = "") -> None:
    print(f"\n{title or result.plan.summary}")
    print(f"Sökte: {'; '.join(result.plan.queries)}  ({result.searched} annonser)")
    for name, err in result.errors.items():
        print(f"  [{PLATFORM_NAMES.get(name, name)} fungerade inte] {err}")
    if not result.matches:
        print("  Inga träffar som passar. Testa att lätta på kraven eller höja maxpriset.")
    for i, l in enumerate(result.matches, 1):
        score = f"{l.score}/10  " if l.score else ""
        details = " · ".join(x for x in (l.brand, f"stl {l.size}" if l.size else "", l.condition) if x)
        print(f"\n{i:>2}. {score}{l.title}  [{PLATFORM_NAMES.get(l.platform, l.platform)}]")
        print(f"    {l.price_local:.0f} {currency}" + (f" ({l.price:.0f} {l.currency})" if l.currency != currency else "")
              + (f" · {details}" if details else ""))
        if l.reason:
            print(f"    {l.reason}")
        print(f"    {l.url}")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9åäö]+", "-", text.lower()).strip("-")[:40] or "sok"


def write_report(settings: FyndSettings, request: str, result: SearchResult) -> Path:
    settings.out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{datetime.now():%Y-%m-%d_%H%M}_{_slug(request)}"
    data = {"request": request, "plan": result.plan.model_dump(), "errors": result.errors,
            "matches": [l.to_dict() for l in result.matches]}
    (settings.out_dir / f"{stem}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    e = html.escape
    cards = []
    for l in result.matches:
        price = f"{l.price_local:.0f} {settings.currency}"
        if l.currency != settings.currency:
            price += f" <small>({l.price:.0f} {e(l.currency)})</small>"
        meta = " · ".join(e(x) for x in (l.brand, f"stl {l.size}" if l.size else "", l.condition) if x)
        img = f'<img src="{e(l.image_url)}" alt="" loading="lazy">' if l.image_url else '<div class="noimg"></div>'
        cards.append(
            f'<a class="card" href="{e(l.url)}" target="_blank" rel="noopener">{img}<div class="body">'
            f'<span class="tag {e(l.platform)}">{e(PLATFORM_NAMES.get(l.platform, l.platform))}</span>'
            + (f'<span class="score">{l.score}/10</span>' if l.score else "")
            + f'<h2>{e(l.title)}</h2><p class="price">{price}</p><p class="meta">{meta}</p>'
            f'<p class="reason">{e(l.reason)}</p></div></a>')
    errors = "".join(f"<p class='err'>{e(PLATFORM_NAMES.get(k, k))} fungerade inte: {e(v)}</p>"
                     for k, v in result.errors.items())
    page = f"""<!doctype html><html lang="sv"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Fynd: {e(request[:60])}</title>
<style>
:root{{--bg:#f6f5f2;--card:#fff;--text:#1d1d1f;--muted:#6b6b70;--line:#e4e2dc}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151517;--card:#202024;--text:#f2f2f2;--muted:#a0a0a8;--line:#333}}}}
body{{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 system-ui,sans-serif;padding:24px 16px}}
header{{max-width:1100px;margin:0 auto 20px}} h1{{font-size:22px;margin:0 0 6px}} header p{{color:var(--muted);margin:2px 0}}
.grid{{max-width:1100px;margin:0 auto;display:grid;gap:16px;grid-template-columns:repeat(auto-fill,minmax(230px,1fr))}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;color:inherit;text-decoration:none}}
.card img,.noimg{{width:100%;aspect-ratio:4/5;object-fit:cover;background:var(--line);display:block}}
.body{{padding:12px}} h2{{font-size:15px;margin:8px 0 4px}} .price{{font-weight:700;margin:0}}
.meta,.reason{{color:var(--muted);margin:4px 0 0;font-size:13px}}
.tag{{font-size:12px;padding:2px 8px;border-radius:99px;background:var(--line)}} .score{{float:right;font-weight:700}}
.vinted{{background:#d6f0ee;color:#055}} .depop{{background:#fde0e0;color:#811}} .grailed{{background:#e3e3e3;color:#222}}
.err{{color:#b3261e}}
</style></head><body><header><h1>{e(result.plan.summary)}</h1>
<p>Du bad om: {e(request)}</p><p>Sökord: {e('; '.join(result.plan.queries))} · {result.searched} annonser genomsökta</p>
{errors}</header><main class="grid">{''.join(cards) or '<p>Inga träffar som passar.</p>'}</main></body></html>"""
    path = settings.out_dir / f"{stem}.html"
    path.write_text(page, encoding="utf-8")
    return path
