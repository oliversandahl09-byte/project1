"""Step 6: three title + thumbnail variants, and Claude picks the strongest one."""
from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from . import ffmpeg
from .config import Settings
from .llm import Claude
from .models import PackagingChoice, PackagingVariant, PackagingVariants, Script
from .prompts import SYSTEM

log = logging.getLogger(__name__)

TW, TH = 1080, 1920
SYSTEM_FONTS = [
    "/usr/share/fonts/opentype/inter/Inter-ExtraBold.otf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]
ACCENTS = [(255, 216, 64), (255, 255, 255), (120, 220, 255)]


def find_font(settings: Settings) -> str | None:
    if settings.font_path and Path(settings.font_path).exists():
        return settings.font_path
    for p in sorted(settings.fonts_dir.glob("*")):
        if p.suffix.lower() in {".ttf", ".otf"} and "bold" in p.name.lower():
            return str(p)
    for p in SYSTEM_FONTS:
        if Path(p).exists():
            return p
    return None


def _font(path: str | None, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return ImageFont.truetype(path, size) if path else ImageFont.load_default(size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    lines, current = [], ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def extract_frames(video: Path, duration: float, out_dir: Path, count: int = 3) -> list[Path]:
    frames = []
    for i in range(count):
        t = duration * (0.15 + 0.3 * i)
        dest = out_dir / f"frame_{i}.jpg"
        ffmpeg.run(["-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1", "-q:v", "2", str(dest)])
        frames.append(dest)
    return frames


def render_thumbnail(frame: Path, text: str, dest: Path, font_path: str | None, accent=(255, 216, 64)) -> Path:
    img = Image.open(frame).convert("RGB").resize((TW, TH))
    img = ImageEnhance.Contrast(img).enhance(1.15)
    # Darken toward the middle so the text pops.
    shade = Image.new("L", (TW, TH), 0)
    sd = ImageDraw.Draw(shade)
    for y in range(TH):
        dist = abs(y - TH * 0.42) / (TH * 0.5)
        sd.line([(0, y), (TW, y)], fill=int(170 * max(0.0, 1 - dist)))
    img = Image.composite(Image.new("RGB", (TW, TH), (0, 0, 0)), img, shade)

    draw = ImageDraw.Draw(img)
    size = 150
    while size > 70:
        font = _font(font_path, size)
        lines = _wrap(draw, text.upper(), font, TW - 140)
        if len(lines) <= 3:
            break
        size -= 10
    line_h = int(size * 1.1)
    y = int(TH * 0.42 - line_h * len(lines) / 2)
    for i, line in enumerate(lines):
        w = draw.textlength(line, font=font)
        color = accent if i == len(lines) - 1 else (255, 255, 255)
        draw.text(((TW - w) / 2, y), line, font=font, fill=color, stroke_width=max(6, size // 14), stroke_fill=(0, 0, 0))
        y += line_h
    img.save(dest, "JPEG", quality=90, optimize=True)
    return dest


def choose_packaging(claude: Claude, settings: Settings, context: str, script: Script,
                     video: Path, duration: float, out_dir: Path) -> tuple[PackagingVariant, Path, dict]:
    prompt = (
        f"{context}\n\n<script>\n{script.full_text}\n</script>\n\n"
        "Create exactly 3 different title + thumbnail-text variants for this Short. Make them clickable "
        "through curiosity, specificity or a bold claim the video actually backs up. No clickbait that "
        "misleads. Titles max 70 characters; each variant should use a different angle. "
        "Follow the style guide's title & thumbnail style."
    )
    variants = claude.structured(SYSTEM, prompt, PackagingVariants).variants[:3]
    if not variants:
        raise ValueError("Inga titelvarianter genererades")

    frames = extract_frames(video, duration, out_dir / "build", count=len(variants))
    font_path = find_font(settings)
    thumbs, previews = [], []
    for i, (v, frame) in enumerate(zip(variants, frames)):
        thumb = render_thumbnail(frame, v.thumbnail_text, out_dir / f"thumbnail_{i}.jpg", font_path, ACCENTS[i % 3])
        preview = out_dir / f"thumbnail_{i}_preview.jpg"
        Image.open(thumb).resize((TW // 3, TH // 3)).save(preview, "JPEG", quality=80)
        thumbs.append(thumb)
        previews.append(preview)

    listing = "\n".join(f"Variant {i} (image {i + 1}): title='{v.title}' thumbnail_text='{v.thumbnail_text}'"
                        for i, v in enumerate(variants))
    choice = claude.structured(
        SYSTEM,
        f"{context}\n\nThe images are the thumbnails in order.\n{listing}\n\n"
        "Act as a ruthless CTR judge. Considering readability on a phone, curiosity gap, honesty versus the "
        "script, and fit with the style guide, pick the single best variant.",
        PackagingChoice,
        images=previews,
    )
    idx = choice.best_index if 0 <= choice.best_index < len(variants) else 0
    log.info("Vald titel: %s (%s)", variants[idx].title, choice.reasoning[:120])
    report = {"variants": [v.model_dump() for v in variants], "chosen": idx, "reasoning": choice.reasoning,
              "thumbnails": [str(t) for t in thumbs]}
    return variants[idx], thumbs[idx], report
