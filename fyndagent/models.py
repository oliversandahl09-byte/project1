"""Data shapes: what Claude returns, and one listing as every marketplace is normalized to."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from pydantic import BaseModel, Field

PLATFORMS = ("vinted", "depop", "grailed")


class SearchPlan(BaseModel):
    summary: str = Field(description="One Swedish sentence: what the user is looking for")
    queries: list[str] = Field(description="1-3 short marketplace search strings (brand + item + key detail), "
                                           "e.g. 'carhartt detroit jacket black'. English works on all sites.")
    max_price: float = Field(description="Max price in the user's currency, 0 if not stated")
    min_price: float = Field(description="Min price in the user's currency, 0 if not stated")
    sizes: list[str] = Field(description="Acceptable sizes as the user stated them (e.g. 'M', '42', 'W32'); empty = any")
    brands: list[str] = Field(description="Wanted brands; empty = any")
    must_have: list[str] = Field(description="Hard requirements besides size/brand/price (colour, model, material...)")
    nice_to_have: list[str] = Field(description="Soft wishes that should raise the ranking")
    avoid: list[str] = Field(description="Things the user does not want (damage, fakes, a colour...)")
    platforms: list[str] = Field(description="Subset of vinted, depop, grailed the user asked for; empty = all")


class Verdict(BaseModel):
    index: int = Field(description="Index of the listing in the candidate list")
    score: int = Field(description="0-10, how well it matches the request (10 = exactly what they want)")
    reason: str = Field(description="Short Swedish reason, mention any doubt (size unclear, possible fake...)")


class Ranking(BaseModel):
    verdicts: list[Verdict] = Field(description="Only listings scoring 5 or more, best first")


@dataclass
class Listing:
    platform: str
    id: str
    title: str
    price: float
    currency: str
    url: str
    image_url: str = ""
    brand: str = ""
    size: str = ""
    condition: str = ""
    seller: str = ""
    description: str = ""
    price_local: float = 0.0  # price converted to the user's currency (approximate)
    score: int = 0
    reason: str = ""

    @property
    def key(self) -> str:
        return f"{self.platform}:{self.id}"

    def to_dict(self) -> dict:
        return asdict(self)
