"""Klipper ut en höjdpunkt som vertikal 1080x1920-video med undertexter och rubrik."""
from __future__ import annotations

import logging
from pathlib import Path

from ytagent import ffmpeg
from ytagent.editor import _ass_escape, _ass_time, filter_path

from .models import ClipEdit, Word

log = logging.getLogger(__name__)

W, H, FPS = 1080, 1920, 30
FONT = "Inter"
WORDS_PER_LINE = 3
ACTIVE = "&H0000E5FF&"  # TikTok-gul för ordet som sägs just nu (ASS är BGR)


def build_ass(words: list[Word], edit: ClipEdit) -> str:
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{FONT},86,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,6,2,2,70,70,520,1
Style: Title,{FONT},70,&H00000000,&H00000000,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,0,0,3,16,0,8,90,90,230,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    length = (edit.end - edit.start) / edit.speed
    lines = []
    if edit.show_title and edit.title.strip():
        lines.append(f"Dialogue: 1,{_ass_time(0)},{_ass_time(length)},Title,,0,0,0,,"
                     f"{{\\fad(150,150)}}{_ass_escape(edit.title)}")
    if edit.show_captions:
        clip_words = [w for w in words if w.start >= edit.start - 0.05 and w.start < edit.end]
        for i in range(0, len(clip_words), WORDS_PER_LINE):
            group = clip_words[i:i + WORDS_PER_LINE]
            for j, w in enumerate(group):
                start = (w.start - edit.start) / edit.speed
                nxt = group[j + 1].start if j + 1 < len(group) else w.end
                end = (min(nxt, edit.end) - edit.start) / edit.speed
                if end <= start:
                    continue
                text = " ".join(
                    f"{{\\c{ACTIVE}}}{_ass_escape(g.text)}{{\\c&H00FFFFFF&}}" if k == j else _ass_escape(g.text)
                    for k, g in enumerate(group)
                )
                lines.append(f"Dialogue: 0,{_ass_time(max(start, 0))},{_ass_time(end)},Caption,,0,0,0,,{text}")
    return header + "\n".join(lines) + "\n"


def video_filter(edit: ClipEdit, ass: str) -> str:
    speed = f"setpts=PTS/{edit.speed}," if edit.speed != 1 else ""
    if edit.layout == "crop":
        x = min(max(edit.crop_x, 0.0), 1.0)
        return (f"[0:v]{speed}scale={W}:{H}:force_original_aspect_ratio=increase,"
                f"crop={W}:{H}:(iw-{W})*{x:.3f}:(ih-{H})/2,fps={FPS},setsar=1,{ass}[v]")
    return (f"[0:v]{speed}split[a][b];"
            f"[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=30:3,"
            f"eq=brightness=-0.12[bg];"
            f"[b]scale={W}:{H}:force_original_aspect_ratio=decrease[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,fps={FPS},setsar=1,{ass}[v]")


def audio_filter(edit: ClipEdit) -> str:
    length = (edit.end - edit.start) / edit.speed
    tempo = f"atempo={edit.speed}," if edit.speed != 1 else ""
    return (f"[0:a]{tempo}afade=t=in:d=0.15,afade=t=out:st={max(length - 0.3, 0):.2f}:d=0.3,"
            f"loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a]")


def render(source: Path, words: list[Word], edit: ClipEdit, out_path: Path,
           fonts_dir: Path | None = None) -> Path:
    ffmpeg.require_ffmpeg()
    if not 0.5 <= edit.speed <= 2.0:
        raise ValueError("Hastigheten måste vara mellan 0.5 och 2")
    if edit.end - edit.start < 1:
        raise ValueError("Klippet måste vara minst 1 sekund")
    work = out_path.parent
    work.mkdir(parents=True, exist_ok=True)
    ass_file = out_path.with_suffix(".ass")
    ass_file.write_text(build_ass(words, edit), encoding="utf-8")
    ass = f"ass={filter_path(ass_file, work)}"
    if fonts_dir and any(p.suffix.lower() in {".ttf", ".otf"} for p in fonts_dir.glob("*")):
        ass += f":fontsdir={filter_path(fonts_dir, work)}"

    length = (edit.end - edit.start) / edit.speed
    ffmpeg.run([
        "-ss", f"{edit.start:.3f}", "-t", f"{edit.end - edit.start:.3f}", "-i", str(source.resolve()),
        "-filter_complex", f"{video_filter(edit, ass)};{audio_filter(edit)}",
        "-map", "[v]", "-map", "[a]", "-t", f"{length:.3f}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out_path.resolve()),
    ], cwd=work)
    log.info("Klipp klart: %s (%.1fs)", out_path, length)
    return out_path
