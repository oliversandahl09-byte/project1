"""End-to-end test with fake Claude/TTS/Pexels: exercises the real ffmpeg edit and thumbnails."""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from ytagent import ffmpeg, pipeline
from ytagent.brief import parse_brief
from ytagent.config import Settings
from ytagent.editor import caption_chunks
from ytagent.history import max_similarity
from ytagent.media import Clip
from ytagent.models import (IdeaList, Idea, Lessons, Metadata, PackagingChoice, PackagingVariant,
                            PackagingVariants, Script, Segment, TaskInterpretation)

BRIEF = """# Channel
Calm explainers for teens.

## Niches

### Deep ocean
Strange deep sea facts.

### Space
Space mysteries.

## Settings
- videos_per_run: 2
- target_length_seconds: 20
- language: English
"""


class FakeClaude:
    def __init__(self):
        self.calls = []

    def text(self, system, prompt):
        return "# Style guide\n## Identity\nCalm deep-sea channel."

    def structured(self, system, prompt, schema, images=None):
        self.calls.append(schema.__name__)
        if schema is IdeaList:
            return IdeaList(ideas=[Idea(title_working="Why the deep sea glows", angle="a", viewer_payoff="b"),
                                   Idea(title_working="The loneliest whale", angle="c", viewer_payoff="d")])
        if schema is Script:
            seg = lambda n, q: Segment(narration=n, on_screen_text="Look closer", visual_query=q)
            if "glow" in prompt:
                lines = ["Most creatures down here make their own light.", "Anglerfish dangle glowing lures.",
                         "Jellyfish flash blue alarms when attacked."]
            else:
                lines = ["One whale sings at a frequency nobody answers.", "Researchers tracked her calls for decades.",
                         "Maybe she is simply different, not lonely."]
            return Script(hook=seg(lines[0], "jellyfish"), body=[seg(t, "ocean") for t in lines[1:]],
                          cta=seg("Follow for part two.", "sea"), sources_or_notes="NOAA")
        if schema is PackagingVariants:
            assert "Create exactly 3" in prompt
            return PackagingVariants(variants=[PackagingVariant(title=f"Title {i}", thumbnail_text=f"Big text {i}",
                                                                rationale="r") for i in range(3)])
        if schema is PackagingChoice:
            assert images and len(images) == 3
            return PackagingChoice(best_index=1, reasoning="clearest")
        if schema is Metadata:
            return Metadata(description="Deep sea light.", tags=["ocean", "deep sea"])
        if schema is TaskInterpretation:
            return TaskInterpretation(count=3, niche="black holes", niche_description="Black hole facts",
                                      style_notes="mysterious", matches_existing_niche="Space")
        if schema is Lessons:
            return Lessons(summary="Hooks with questions win.", what_works=["question hooks (video A)"],
                           what_doesnt=["slow intros"], per_niche=["Space: strong"], experiments=["shorter hook"],
                           confidence="low")
        raise AssertionError(schema)


def fake_voice(settings, texts, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    result = []
    for i, _ in enumerate(texts):
        p = out_dir / f"voice_{i:02d}.mp3"
        ffmpeg.run(["-f", "lavfi", "-i", "sine=frequency=440:duration=1.5", str(p)])
        result.append((p, ffmpeg.probe_duration(p)))
    return result


def fake_clips(settings, queries, durations, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    video = out_dir / "clip.mp4"
    ffmpeg.run(["-f", "lavfi", "-i", "testsrc=size=720x1280:rate=30:duration=1", "-pix_fmt", "yuv420p", str(video)])
    photo = out_dir / "photo.jpg"
    Image.new("RGB", (800, 1200), (20, 60, 90)).save(photo)
    kinds = [Clip(video, "video", "Video by A on Pexels"), Clip(photo, "photo", "Photo by B on Pexels"), Clip(None, "none")]
    return [kinds[i % 3] for i in range(len(queries))]


def test_full_run_without_upload(tmp_path: Path, monkeypatch):
    (tmp_path / "brief.md").write_text(BRIEF)
    settings = Settings(root=tmp_path, google_client_secret=tmp_path / "x", google_token=tmp_path / "y")
    monkeypatch.setattr(pipeline, "synthesize_segments", fake_voice)
    monkeypatch.setattr(pipeline, "fetch_clips", fake_clips)

    result = pipeline.Pipeline(settings, claude=FakeClaude()).run(upload=False)

    assert not result.failed, result.failed
    assert len(result.succeeded) == 2
    entry = result.succeeded[0]
    video = Path(entry["video"])
    assert video.exists() and ffmpeg.probe_duration(video) > 5
    assert entry["title"] == "Title 1"  # Claude picked index 1
    work = Path(entry["dir"])
    meta = json.loads((work / "metadata.json").read_text())
    assert "#Shorts" in meta["description"] and "AI-generated voice" in meta["description"]
    assert "Pexels" in meta["description"]
    assert len(list(work.glob("thumbnail_?.jpg"))) == 3
    assert (tmp_path / "style_guide.md").exists()
    assert len(json.loads((tmp_path / "data" / "history.json").read_text())) == 2


def test_one_failure_does_not_stop_the_rest(tmp_path: Path, monkeypatch):
    (tmp_path / "brief.md").write_text(BRIEF)
    settings = Settings(root=tmp_path)
    calls = {"n": 0}

    def flaky_voice(settings, texts, out_dir):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("TTS down")
        return fake_voice(settings, texts, out_dir)

    monkeypatch.setattr(pipeline, "synthesize_segments", flaky_voice)
    monkeypatch.setattr(pipeline, "fetch_clips", fake_clips)
    result = pipeline.Pipeline(settings, claude=FakeClaude()).run(upload=False)
    assert len(result.failed) == 1 and len(result.succeeded) == 1


def test_brief_settings():
    b = parse_brief(BRIEF)
    assert b.video_count == 2 and b.target_seconds == 20 and b.language == "English"


def test_caption_chunks_cover_duration():
    chunks = caption_chunks("one two three four five six seven", 2.0, 3.0)
    assert chunks[0][0] == 2.0 and len(chunks) == 3
    assert abs(chunks[-1][1] - (2.0 + 3.0 - 0.15)) < 1e-6


def test_similarity_blocks_repeats():
    text = "the anglerfish uses a glowing lure to hunt in total darkness"
    assert max_similarity(text, [{"script": text}]) == 1.0
    assert max_similarity(text, [{"script": "whales sing songs across entire oceans"}]) < 0.1
