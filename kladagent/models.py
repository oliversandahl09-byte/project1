"""Data shapes for a search: what you ask for and what the agent reports back."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

Platform = Literal["vinted", "depop", "grailed"]


@dataclass
class Image:
    media_type: str
    data: bytes


@dataclass
class SearchRequest:
    text: str = ""
    images: list[Image] = field(default_factory=list)
    platforms: list[str] = field(default_factory=lambda: ["vinted", "depop", "grailed"])
    max_price: int | None = None
    size: str = ""
    gender: str = ""  # "dam", "herr" or "" for both
    # Earlier turns in the same chat, oldest first: {"role": "user" | "agent", "text": "..."}
    history: list[dict] = field(default_factory=list)


class Listing(BaseModel):
    platform: Platform
    title: str
    url: str
    price: str | None = None
    size: str | None = None
    brand: str | None = None
    condition: str | None = None
    image_url: str | None = None
    why: str = ""
    match_score: int = Field(default=5, ge=1, le=10)


class Report(BaseModel):
    """The input of the report_results tool Claude calls when it is done searching."""
    style_summary: str
    message: str
    queries: list[str]
    listings: list[Listing]


class SearchLink(BaseModel):
    platform: Platform
    query: str
    url: str


class SearchResult(BaseModel):
    style_summary: str
    message: str
    queries: list[str]
    listings: list[Listing]
    search_links: list[SearchLink]
