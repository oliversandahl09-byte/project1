"""Data shapes that Claude returns and the pipeline passes between steps."""
from __future__ import annotations

from pydantic import BaseModel, Field


class Idea(BaseModel):
    title_working: str = Field(description="Working title")
    angle: str = Field(description="What makes this video unique and valuable, in one or two sentences")
    viewer_payoff: str = Field(description="What the viewer learns or gets by watching to the end")


class IdeaList(BaseModel):
    ideas: list[Idea]


class Segment(BaseModel):
    narration: str = Field(description="Exactly what the narrator says in this segment")
    on_screen_text: str = Field(description="Short punchy overlay text (max 6 words), or empty")
    visual_query: str = Field(description="2-4 word English search query for stock footage, concrete and visual")


class Script(BaseModel):
    hook: Segment = Field(description="First ~3-5 seconds. Must stop the scroll.")
    body: list[Segment]
    cta: Segment = Field(description="Clear call to action at the end")
    sources_or_notes: str = Field(description="Facts used and where they come from, for the description. Empty if none.")

    @property
    def segments(self) -> list[Segment]:
        return [self.hook, *self.body, self.cta]

    @property
    def full_text(self) -> str:
        return " ".join(s.narration for s in self.segments)


class PackagingVariant(BaseModel):
    title: str = Field(description="YouTube title, max 70 characters")
    thumbnail_text: str = Field(description="2-5 words of big thumbnail text")
    rationale: str


class PackagingVariants(BaseModel):
    variants: list[PackagingVariant]


class PackagingChoice(BaseModel):
    best_index: int = Field(description="0-based index of the best variant")
    reasoning: str


class Metadata(BaseModel):
    description: str = Field(description="YouTube description, first line is a hook, includes hashtags at the end")
    tags: list[str] = Field(description="10-15 relevant tags")


class TaskInterpretation(BaseModel):
    count: int = Field(description="How many videos the user asked for; 0 if not stated")
    niche: str = Field(description="Topic/niche of the videos, short (e.g. 'space mysteries')")
    niche_description: str = Field(description="One or two sentences describing the niche and its angle")
    style_notes: str = Field(description="Any style, tone or format wishes in the request, in English; empty if none")
    matches_existing_niche: str = Field(description="Name of the matching niche from the brief, or empty")


class Lessons(BaseModel):
    summary: str = Field(description="2-4 sentence overview of channel performance so far")
    what_works: list[str] = Field(description="Concrete patterns linked to strong retention/engagement, with evidence")
    what_doesnt: list[str] = Field(description="Concrete patterns linked to weak results, with evidence")
    per_niche: list[str] = Field(description="One line per niche: how it performs and what to do next")
    experiments: list[str] = Field(description="2-4 specific things to test in the next videos")
    confidence: str = Field(description="low / medium / high, given the amount of data")
