"""Step 5: edit the Short with ffmpeg.

1. One silent 1080x1920 video per segment, cut to the exact voice duration.
2. Concatenate video and voice.
3. Burn in captions (word groups) and on-screen text, mix optional background music.
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from pathlib import Path

from . import ffmpeg
from .media import Clip

log = logging.getLogger(__name__)

W, H, FPS = 1080, 1920, 30
FONT_NAME = "Inter"
MUSIC_VOLUME = 0.12
GRADE = "eq=contrast=1.05:saturation=0.92:brightness=-0.02"  # calm, slightly muted look


@dataclass
class SegmentInput:
    narration: str
    on_screen_text: str
    voice: Path
    duration: float
    clip: Clip


def _render_segment(seg: SegmentInput, dest: Path) -> None:
    d = f"{seg.duration:.3f}"
    frames = int(seg.duration * FPS) + 1
    common_out = ["-an", "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                  "-pix_fmt", "yuv420p", str(dest)]
    if seg.clip.kind == "video":
        vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
              f"fps={FPS},setsar=1,{GRADE}")
        ffmpeg.run(["-stream_loop", "-1", "-i", str(seg.clip.path), "-t", d, "-vf", vf, *common_out])
    elif seg.clip.kind == "photo":
        # Slow Ken Burns zoom so photos feel alive.
        vf = (f"scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase,crop={W * 2}:{H * 2},"
              f"zoompan=z='min(zoom+0.0007,1.12)':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
              f":s={W}x{H}:fps={FPS},setsar=1,{GRADE}")
        ffmpeg.run(["-i", str(seg.clip.path), "-t", d, "-vf", vf, *common_out])
    else:
        ffmpeg.run(["-f", "lavfi", "-i", f"gradients=s={W}x{H}:r={FPS}:c0=0x0f1a24:c1=0x2a3b4c:speed=0.002",
                    "-t", d, "-vf", "setsar=1", *common_out])


def _ass_time(t: float) -> str:
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _ass_escape(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ").strip()


def caption_chunks(text: str, start: float, duration: float, max_words: int = 3) -> list[tuple[float, float, str]]:
    """Split narration into short word groups, timed in proportion to their length."""
    words = text.split()
    if not words:
        return []
    groups = [" ".join(words[i:i + max_words]) for i in range(0, len(words), max_words)]
    weights = [len(g) + 2 for g in groups]
    total = sum(weights)
    usable = max(duration - 0.15, 0.1)
    out, t = [], start
    for g, w in zip(groups, weights):
        dt = usable * w / total
        out.append((t, t + dt, g))
        t += dt
    return out


def build_ass(segments: list[SegmentInput]) -> str:
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{FONT_NAME},84,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,5,2,2,80,80,560,1
Style: Overlay,{FONT_NAME},72,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,-1,0,0,0,100,100,1,0,3,18,0,8,90,90,260,1
Style: Hook,{FONT_NAME},92,&H0040D8FF,&H0040D8FF,&H00000000,&H96000000,-1,0,0,0,100,100,1,0,3,20,0,8,80,80,300,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    t = 0.0
    for i, seg in enumerate(segments):
        if seg.on_screen_text.strip():
            style = "Hook" if i == 0 else "Overlay"
            text = _ass_escape(seg.on_screen_text).upper()
            lines.append(f"Dialogue: 1,{_ass_time(t)},{_ass_time(t + seg.duration)},{style},,0,0,0,,{{\\fad(120,120)}}{text}")
        for start, end, chunk in caption_chunks(seg.narration, t, seg.duration):
            lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Caption,,0,0,0,,{_ass_escape(chunk)}")
        t += seg.duration
    return header + "\n".join(lines) + "\n"


def _pick_music(music_dir: Path) -> Path | None:
    tracks = [p for p in music_dir.glob("*") if p.suffix.lower() in {".mp3", ".wav", ".m4a", ".ogg"}]
    return random.choice(tracks) if tracks else None


def render_short(segments: list[SegmentInput], work_dir: Path, out_path: Path,
                 music_dir: Path | None = None, fonts_dir: Path | None = None) -> Path:
    ffmpeg.require_ffmpeg()
    work_dir.mkdir(parents=True, exist_ok=True)

    seg_files = []
    for i, seg in enumerate(segments):
        dest = work_dir / f"seg_{i:02d}.mp4"
        _render_segment(seg, dest)
        seg_files.append(dest)

    (work_dir / "video_list.txt").write_text("".join(f"file '{p.name}'\n" for p in seg_files))
    ffmpeg.run(["-f", "concat", "-safe", "0", "-i", "video_list.txt", "-c", "copy", "video.mp4"], cwd=work_dir)

    voice_inputs: list[str] = []
    for seg in segments:
        voice_inputs += ["-i", str(seg.voice.resolve())]
    n = len(segments)
    ffmpeg.run([*voice_inputs, "-filter_complex",
                "".join(f"[{i}:a]" for i in range(n)) + f"concat=n={n}:v=0:a=1,aresample=48000[a]",
                "-map", "[a]", "-c:a", "pcm_s16le", "voice.wav"], cwd=work_dir)

    (work_dir / "captions.ass").write_text(build_ass(segments), encoding="utf-8")
    total = sum(s.duration for s in segments)
    ass = "ass=captions.ass"
    if fonts_dir and fonts_dir.exists():
        ass += f":fontsdir={fonts_dir.resolve()}"

    music = _pick_music(music_dir) if music_dir else None
    args = ["-i", "video.mp4", "-i", "voice.wav"]
    if music:
        log.info("Bakgrundsmusik: %s", music.name)
        args += ["-stream_loop", "-1", "-i", str(music.resolve())]
        fade_start = max(total - 1.5, 0)
        audio = (f"[2:a]volume={MUSIC_VOLUME},afade=t=in:d=1,afade=t=out:st={fade_start:.2f}:d=1.5[m];"
                 f"[1:a][m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
                 f"loudnorm=I=-14:TP=-1.5:LRA=11[a]")
    else:
        audio = "[1:a]loudnorm=I=-14:TP=-1.5:LRA=11[a]"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg.run([*args, "-filter_complex", f"[0:v]{ass}[v];{audio}", "-map", "[v]", "-map", "[a]",
                "-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                "-movflags", "+faststart", str(out_path.resolve())], cwd=work_dir)
    log.info("Video klar: %s (%.1fs)", out_path, total)
    return out_path
