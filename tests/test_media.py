"""Stock footage selection without network: fake API responses."""
from pathlib import Path

from ytagent.media import Pixabay, fetch_clips
from ytagent.config import Settings


def _hit(i, w, h, duration=20):
    return {"id": i, "duration": duration, "user": f"user{i}", "pageURL": f"https://pixabay.com/{i}",
            "videos": {"large": {"url": f"https://cdn/{i}.mp4", "width": w, "height": h},
                       "small": {"url": f"https://cdn/{i}s.mp4", "width": w // 3, "height": h // 3}}}


class FakePixabay(Pixabay):
    def __init__(self, hits, photos=()):
        super().__init__("key")
        self.hits, self.photos, self.downloaded = hits, list(photos), []

    def _get(self, url, params):
        assert params["safesearch"] == "true"
        return {"hits": self.hits if "videos" in url else self.photos}

    def _download(self, url, dest):
        self.downloaded.append(url)
        return dest


def test_pixabay_prefers_vertical_and_sharp(tmp_path: Path):
    src = FakePixabay([_hit(1, 1920, 1080), _hit(2, 1080, 1920)])
    clip = src.find_video("shark", 5, tmp_path / "c.mp4")
    assert clip.kind == "video" and src.downloaded == ["https://cdn/2.mp4"]
    assert "Pixabay" in clip.credit
    # Same clip is not reused within one video.
    src.find_video("shark", 5, tmp_path / "d.mp4")
    assert src.downloaded[-1] == "https://cdn/1.mp4"


def test_falls_back_to_photo_then_background(tmp_path: Path):
    photo = {"id": 9, "largeImageURL": "https://cdn/p.jpg", "user": "u", "pageURL": "x"}
    clips = fetch_clips(Settings(root=tmp_path), ["deep sea", "void"], [3, 3], tmp_path,
                        sources=[FakePixabay([], [photo])])
    assert clips[0].kind == "photo"
    assert clips[1].kind == "none"  # photo already used, nothing else found


def test_missing_ffmpeg_fails_fast(monkeypatch, tmp_path):
    import pytest
    from ytagent import ffmpeg, pipeline

    monkeypatch.setattr(ffmpeg.shutil, "which", lambda name: None)
    with pytest.raises(ffmpeg.FFmpegError, match="winget install"):
        pipeline.Pipeline(Settings(root=tmp_path), claude=object()).run()


def test_filter_path_is_relative_and_parser_safe(tmp_path: Path):
    from ytagent.editor import filter_path

    fonts, work = tmp_path / "assets" / "fonts", tmp_path / "output" / "x" / "build"
    fonts.mkdir(parents=True)
    work.mkdir(parents=True)
    result = filter_path(fonts, work)
    assert result == "../../../assets/fonts"
    assert ":" not in result and "\\" not in result
