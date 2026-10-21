"""The marketplaces the agent searches: domains, search links and URL checks."""
from __future__ import annotations

from urllib.parse import quote_plus, urlparse

PLATFORMS = ("vinted", "depop", "grailed")


def domains(vinted_domain: str) -> dict[str, str]:
    return {"vinted": vinted_domain, "depop": "depop.com", "grailed": "grailed.com"}


def search_url(platform: str, query: str, vinted_domain: str, max_price: int | None = None) -> str:
    """A link to the platform's own search page, so you can always keep browsing yourself."""
    q = quote_plus(query)
    if platform == "vinted":
        url = f"https://www.{vinted_domain}/catalog?search_text={q}&order=relevance"
        return url + f"&price_to={max_price}" if max_price else url
    if platform == "depop":
        url = f"https://www.depop.com/search/?q={q}"
        return url + f"&priceMax={max_price}" if max_price else url
    if platform == "grailed":
        return f"https://www.grailed.com/shop?query={q}"
    raise ValueError(f"Okänd plattform: {platform}")


def platform_of(url: str, vinted_domain: str) -> str | None:
    """Which platform a URL belongs to, or None if it is somewhere else."""
    host = (urlparse(url).hostname or "").lower()
    for name, domain in domains(vinted_domain).items():
        if host == domain or host.endswith("." + domain):
            return name
    return None


def normalize(url: str) -> str:
    p = urlparse(url)
    return f"{(p.hostname or '').lower().removeprefix('www.')}{p.path.rstrip('/')}"
