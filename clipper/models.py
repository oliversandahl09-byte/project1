"""Data for a clip job, stored as output/clips/<job_id>/job.json."""
from __future__ import annotations

from pydantic import BaseModel, Field


class Word(BaseModel):
    start: float
    end: float
    text: str


class Highlight(BaseModel):
    start: float = Field(description="Starttid i sekunder")
    end: float = Field(description="Sluttid i sekunder")
    title: str = Field(description="Kort, fängslande text som visas överst i klippet (max ca 6 ord)")
    reason: str = Field(description="Varför detta är en höjdpunkt")
    score: int = Field(description="1-10, hur troligt det är att klippet går bra på TikTok")
    caption: str = Field(description="TikTok-beskrivning med 3-5 relevanta hashtags")


class HighlightList(BaseModel):
    highlights: list[Highlight]


class ClipEdit(BaseModel):
    """What the user chose in the editor for one highlight."""
    start: float
    end: float
    title: str = ""
    caption: str = ""
    layout: str = "blur"        # blur = hela bilden med suddig bakgrund, crop = fyll skärmen
    crop_x: float = 0.5         # 0 = vänsterkant, 1 = högerkant (bara för crop)
    show_title: bool = True
    show_captions: bool = True
    speed: float = 1.0


class Clip(BaseModel):
    id: str
    highlight: Highlight
    edit: ClipEdit
    status: str = "suggested"   # suggested | rendering | rendered | uploading | uploaded | failed
    file: str = ""
    error: str = ""
    tiktok_publish_id: str = ""
    tiktok_status: str = ""


class Job(BaseModel):
    id: str
    url: str
    status: str = "queued"      # queued | downloading | transcribing | analyzing | ready | failed
    message: str = ""
    title: str = ""
    duration: float = 0.0
    source: str = ""            # downloaded video, relative to the job folder
    transcript_source: str = "" # youtube | whisper | none
    highlight_method: str = ""  # claude | audio
    clips: list[Clip] = []
    created: str = ""
