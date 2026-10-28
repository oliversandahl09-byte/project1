"""TikTok Content Posting API: inloggning (OAuth) och uppladdning.

Två lägen (TIKTOK_MODE):
- inbox:  klippet hamnar som utkast i TikTok-appen, där du lägger till ljud/text och publicerar.
          Kräver scope video.upload och fungerar innan appen är granskad av TikTok.
- direct: publiceras direkt. Kräver scope video.publish. Ogranskade appar får bara posta privat (SELF_ONLY).
"""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode

import requests

log = logging.getLogger(__name__)

AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
API = "https://open.tiktokapis.com/v2"
CHUNK = 10 * 1024 * 1024
MAX_SINGLE = 64 * 1024 * 1024


class TikTokError(RuntimeError):
    pass


class TikTok:
    def __init__(self, client_key: str, client_secret: str, redirect_uri: str, token_file: Path,
                 mode: str = "inbox", privacy: str = "SELF_ONLY"):
        self.client_key = client_key
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.token_file = token_file
        self.mode = mode
        self.privacy = privacy
        self._pending: dict[str, str] = {}  # state -> PKCE verifier

    @property
    def configured(self) -> bool:
        return bool(self.client_key and self.client_secret)

    @property
    def scopes(self) -> str:
        return "user.info.basic," + ("video.publish" if self.mode == "direct" else "video.upload")

    # --- inloggning ---

    def login_url(self) -> str:
        state = secrets.token_urlsafe(16)
        verifier = secrets.token_urlsafe(48)
        self._pending[state] = verifier
        return AUTH_URL + "?" + urlencode({
            "client_key": self.client_key,
            "scope": self.scopes,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "state": state,
            # TikTok vill ha SHA-256 som hex, inte base64url
            "code_challenge": hashlib.sha256(verifier.encode()).hexdigest(),
            "code_challenge_method": "S256",
        })

    def finish_login(self, code: str, state: str) -> None:
        verifier = self._pending.pop(state, None)
        if verifier is None:
            raise TikTokError("Ogiltig inloggning (state stämmer inte). Försök igen.")
        self._save(self._token_request({
            "code": code, "grant_type": "authorization_code",
            "redirect_uri": self.redirect_uri, "code_verifier": verifier,
        }))

    def logged_in(self) -> bool:
        return self.token_file.exists()

    def _token_request(self, data: dict) -> dict:
        r = requests.post(f"{API}/oauth/token/", data={
            "client_key": self.client_key, "client_secret": self.client_secret, **data,
        }, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=30)
        body = r.json() if r.content else {}
        if r.status_code != 200 or "access_token" not in body:
            raise TikTokError(f"TikTok-inloggning misslyckades: {body.get('error_description') or r.text[:300]}")
        body["expires_at"] = time.time() + int(body.get("expires_in", 0)) - 60
        return body

    def _save(self, token: dict) -> None:
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        self.token_file.write_text(json.dumps(token, indent=2))

    def _access_token(self) -> str:
        if not self.token_file.exists():
            raise TikTokError("Inte inloggad på TikTok")
        token = json.loads(self.token_file.read_text())
        if time.time() >= token.get("expires_at", 0):
            token = self._token_request({"grant_type": "refresh_token", "refresh_token": token["refresh_token"]})
            self._save(token)
        return token["access_token"]

    def _post(self, path: str, payload: dict) -> dict:
        r = requests.post(f"{API}{path}", json=payload, timeout=60, headers={
            "Authorization": f"Bearer {self._access_token()}",
            "Content-Type": "application/json; charset=UTF-8",
        })
        body = r.json() if r.content else {}
        err = body.get("error", {})
        if r.status_code != 200 or err.get("code", "ok") != "ok":
            raise TikTokError(f"TikTok-fel ({err.get('code', r.status_code)}): {err.get('message') or r.text[:300]}")
        return body.get("data", {})

    # --- uppladdning ---

    def upload(self, video: Path, caption: str) -> str:
        """Laddar upp videon och returnerar publish_id."""
        size = video.stat().st_size
        if size <= MAX_SINGLE:
            chunk_size, count = size, 1
        else:
            chunk_size, count = CHUNK, size // CHUNK  # sista biten tar resten
        source = {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk_size,
                  "total_chunk_count": count}
        if self.mode == "direct":
            data = self._post("/post/publish/video/init/", {
                "post_info": {"title": caption[:2200], "privacy_level": self.privacy,
                              "disable_comment": False, "disable_duet": False, "disable_stitch": False},
                "source_info": source,
            })
        else:
            data = self._post("/post/publish/inbox/video/init/", {"source_info": source})

        with video.open("rb") as f:
            for i in range(count):
                start = i * chunk_size
                end = size - 1 if i == count - 1 else start + chunk_size - 1
                f.seek(start)
                part = f.read(end - start + 1)
                r = requests.put(data["upload_url"], data=part, timeout=300, headers={
                    "Content-Type": "video/mp4",
                    "Content-Length": str(len(part)),
                    "Content-Range": f"bytes {start}-{end}/{size}",
                })
                if r.status_code not in (200, 201, 206):
                    raise TikTokError(f"Uppladdning av del {i + 1}/{count} misslyckades: {r.status_code} {r.text[:200]}")
        log.info("Uppladdat till TikTok (%s): publish_id %s", self.mode, data["publish_id"])
        return data["publish_id"]

    def status(self, publish_id: str) -> str:
        data = self._post("/post/publish/status/fetch/", {"publish_id": publish_id})
        return data.get("status", "")
