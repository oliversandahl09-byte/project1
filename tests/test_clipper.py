import json
import subprocess
import time
from pathlib import Path

import pytest

from clipper import highlights, render, tiktok, transcript
from clipper.download import Downloaded
from clipper.jobs import Jobs
from clipper.models import ClipEdit, Highlight, Word
from ytagent.config import Settings

AUTO_VTT = """WEBVTT
Kind: captions
Language: en

00:00:00.000 --> 00:00:02.000 align:start position:0%
hello<00:00:00.500><c> world</c><00:00:01.000><c> this</c>

00:00:02.000 --> 00:00:02.010 align:start position:0%
hello world this

00:00:02.010 --> 00:00:04.000 align:start position:0%
hello world this
is<00:00:02.600><c> great</c>
"""

MANUAL_VTT = """WEBVTT

1
00:00:01.000 --> 00:00:03.000
Det här är <i>bra</i>

2
00:00:03.000 --> 00:00:05.000
Det här är <i>bra</i>
"""


def test_parse_auto_captions_word_times():
    words = transcript.parse_vtt(AUTO_VTT)
    assert [w.text for w in words] == ["hello", "world", "this", "is", "great"]
    assert [w.start for w in words] == [0.0, 0.5, 1.0, 2.01, 2.6]
    assert all(w.end > w.start for w in words)


def test_parse_manual_captions_skips_repeats():
    words = transcript.parse_vtt(MANUAL_VTT)
    assert [w.text for w in words] == ["Det", "här", "är", "bra"]
    assert words[0].start == 1.0 and words[-1].end <= 3.0


def test_as_lines():
    words = transcript.parse_vtt(AUTO_VTT)
    assert transcript.as_lines(words).startswith("[00:00] hello world")


def test_clean_snaps_and_drops_overlap():
    words = [Word(start=i, end=i + 0.8, text=f"w{i}") for i in range(100)]
    hs = [
        Highlight(start=10.4, end=30.2, title="a", reason="", score=9, caption=""),
        Highlight(start=20, end=40, title="b", reason="", score=5, caption=""),   # överlappar a
        Highlight(start=50, end=200, title="c", reason="", score=7, caption=""),  # för lång, kortas
    ]
    out = highlights.clean(hs, words, 100, 15, 60)
    assert [h.title for h in out] == ["a", "c"]
    assert out[0].start == 10 and out[0].end == pytest.approx(30.8 + 0.3)
    assert out[1].end - out[1].start <= 60


@pytest.fixture(scope="module")
def source_video(tmp_path_factory) -> Path:
    """40 s liggande testvideo; ljudet är tyst förutom en hög ton vid 20-30 s."""
    path = tmp_path_factory.mktemp("src") / "source.mp4"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=40",
        "-f", "lavfi", "-i", "sine=f=440:d=40",
        "-filter_complex", "[1:a]volume='if(between(t,20,30),1,0.02)':eval=frame[a]",
        "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(path),
    ], check=True)
    return path


def test_audio_fallback_finds_loud_part(source_video):
    hs = highlights.by_audio(source_video, [], count=2, length=10)
    assert 18 <= hs[0].start <= 22


def _probe(path: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration",
                          "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


@pytest.mark.parametrize("layout,speed", [("blur", 1.0), ("crop", 1.25)])
def test_render_vertical(source_video, tmp_path, layout, speed):
    words = [Word(start=5 + i * 0.5, end=5.4 + i * 0.5, text=f"ord{i}") for i in range(20)]
    edit = ClipEdit(start=5, end=15, title="Testrubrik", layout=layout, crop_x=0.2, speed=speed)
    out = render.render(source_video, words, edit, tmp_path / "clip.mp4")
    info = _probe(out)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (video["width"], video["height"]) == (1080, 1920)
    assert any(s["codec_type"] == "audio" for s in info["streams"])
    assert float(info["format"]["duration"]) == pytest.approx(10 / speed, abs=0.3)
    ass = (tmp_path / "clip.ass").read_text()
    assert "Testrubrik" in ass and "ord0" in ass and "ord19" in ass


def test_web_app_end_to_end(source_video, tmp_path):
    from fastapi.testclient import TestClient

    from clipper.server import create_app

    def fake_download(url, dest):
        dest.mkdir(parents=True, exist_ok=True)
        video = dest / "source.mp4"
        video.write_bytes(source_video.read_bytes())
        subs = dest / "source.en.vtt"
        subs.write_text(AUTO_VTT)
        return Downloaded(video=video, title="Testvideo", duration=40.0, subtitles=subs)

    settings = Settings(root=tmp_path)  # ingen Claude-nyckel → ljudnivå
    jobs = Jobs(settings, tmp_path / "clips", downloader=fake_download)
    tt = tiktok.TikTok("", "", "http://localhost/cb", tmp_path / "t.json")
    client = TestClient(create_app(settings, jobs, tt))

    assert client.post("/api/jobs", json={"url": "https://example.com/x"}).status_code == 400
    job = client.post("/api/jobs", json={"url": "https://youtu.be/abc", "count": 2, "min_len": 10, "max_len": 10}).json()
    for _ in range(60):
        job = client.get(f"/api/jobs/{job['id']}").json()
        if job["status"] in {"ready", "failed"}:
            break
        time.sleep(0.5)
    assert job["status"] == "ready", job["message"]
    assert job["transcript_source"] == "youtube" and job["highlight_method"] == "audio"
    assert len(job["clips"]) == 2
    assert client.get(f"/api/jobs/{job['id']}/text", params={"start": 0, "end": 1.5}).json()["text"] == "hello world this"

    clip = job["clips"][0]
    edit = {**clip["edit"], "start": 0, "end": 4, "title": "Hej"}
    assert client.post(f"/api/jobs/{job['id']}/clips/{clip['id']}/render", json={**edit, "end": 999}).status_code == 400
    assert client.post(f"/api/jobs/{job['id']}/clips/{clip['id']}/render", json=edit).status_code == 200
    for _ in range(120):
        c = client.get(f"/api/jobs/{job['id']}").json()["clips"][0]
        if c["status"] != "rendering":
            break
        time.sleep(0.5)
    assert c["status"] == "rendered", c["error"]
    r = client.get(f"/media/{job['id']}/{c['file']}")
    assert r.status_code == 200 and len(r.content) > 1000
    assert client.get(f"/media/{job['id']}/../../etc/passwd").status_code == 404
    assert client.get(f"/media/{job['id']}/words.json").status_code == 404

    added = client.post(f"/api/jobs/{job['id']}/clips", json={"start": 1, "end": 20}).json()
    assert added["id"] == "c3"
    client.delete(f"/api/jobs/{job['id']}/clips/c3")
    assert len(client.get(f"/api/jobs/{job['id']}").json()["clips"]) == 2


class _Resp:
    def __init__(self, status=200, body=None):
        self.status_code, self._body = status, body or {}
        self.content = json.dumps(self._body).encode()
        self.text = self.content.decode()

    def json(self):
        return self._body


def test_tiktok_upload_chunks(tmp_path, monkeypatch):
    token = tmp_path / "token.json"
    token.write_text(json.dumps({"access_token": "abc", "refresh_token": "r", "expires_at": time.time() + 3600}))
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x" * (tiktok.MAX_SINGLE + tiktok.CHUNK + 123))
    calls = []

    def post(url, json=None, **kw):
        calls.append(("POST", url, json))
        return _Resp(body={"data": {"publish_id": "p1", "upload_url": "https://up"}, "error": {"code": "ok"}})

    def put(url, data=None, headers=None, **kw):
        calls.append(("PUT", headers["Content-Range"], len(data)))
        return _Resp(201)

    monkeypatch.setattr(tiktok.requests, "post", post)
    monkeypatch.setattr(tiktok.requests, "put", put)
    tt = tiktok.TikTok("k", "s", "http://localhost/cb", token)
    assert tt.upload(video, "hej #fyp") == "p1"

    size = video.stat().st_size
    init = calls[0]
    assert init[1].endswith("/post/publish/inbox/video/init/")
    count = init[2]["source_info"]["total_chunk_count"]
    puts = [c for c in calls if c[0] == "PUT"]
    assert len(puts) == count == size // tiktok.CHUNK
    assert sum(p[2] for p in puts) == size
    assert puts[-1][1].endswith(f"-{size - 1}/{size}")


def test_tiktok_login_url_has_pkce():
    tt = tiktok.TikTok("key", "secret", "http://localhost:8000/tiktok/callback", Path("x"))
    url = tt.login_url()
    assert "client_key=key" in url and "code_challenge=" in url and "video.upload" in url
    with pytest.raises(tiktok.TikTokError):
        tt.finish_login("code", "wrong-state")
