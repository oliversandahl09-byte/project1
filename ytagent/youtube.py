"""Step 8: OAuth login, upload, thumbnail and publish via YouTube Data API v3."""
from __future__ import annotations

import logging
import time
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from .config import Settings

log = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]
RETRY_STATUS = {500, 502, 503, 504}


def get_credentials(settings: Settings, interactive: bool = True) -> Credentials:
    creds = None
    if settings.google_token.exists():
        creds = Credentials.from_authorized_user_file(str(settings.google_token), SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        if not interactive:
            raise RuntimeError("Ingen giltig YouTube-inloggning. Kör: python -m ytagent auth")
        if not settings.google_client_secret.exists():
            raise FileNotFoundError(
                f"Hittar inte {settings.google_client_secret}. Ladda ner OAuth-klienten från Google Cloud (se README)."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(settings.google_client_secret), SCOPES)
        creds = flow.run_local_server(port=0, prompt="consent")
    settings.google_token.parent.mkdir(parents=True, exist_ok=True)
    settings.google_token.write_text(creds.to_json())
    return creds


def youtube_client(settings: Settings, interactive: bool = False):
    return build("youtube", "v3", credentials=get_credentials(settings, interactive), cache_discovery=False)


def upload_video(settings: Settings, video: Path, title: str, description: str, tags: list[str],
                 category_id: str, language: str = "en", synthetic: bool = True,
                 publish_at: str | None = None) -> str:
    yt = youtube_client(settings)
    status = {
        "privacyStatus": "private",
        "selfDeclaredMadeForKids": False,
        # YouTube's "altered or synthetic content" disclosure.
        "containsSyntheticMedia": synthetic,
    }
    if publish_at:
        status["publishAt"] = publish_at
    body = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "tags": tags,
            "categoryId": category_id,
            "defaultLanguage": language,
            "defaultAudioLanguage": language,
        },
        "status": status,
    }
    media = MediaFileUpload(str(video), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
    request = yt.videos().insert(part="snippet,status", body=body, media_body=media)

    response, retries = None, 0
    while response is None:
        try:
            progress, response = request.next_chunk()
            if progress:
                log.info("Uppladdning %d%%", int(progress.progress() * 100))
        except HttpError as e:
            if e.resp.status in RETRY_STATUS and retries < 5:
                retries += 1
                time.sleep(2 ** retries)
                continue
            raise
    video_id = response["id"]
    log.info("Uppladdad: https://youtu.be/%s", video_id)
    return video_id


def set_thumbnail(settings: Settings, video_id: str, thumbnail: Path) -> bool:
    """Custom thumbnails need a verified channel. Failure is logged, not fatal."""
    try:
        youtube_client(settings).thumbnails().set(
            videoId=video_id, media_body=MediaFileUpload(str(thumbnail), mimetype="image/jpeg")
        ).execute()
        return True
    except HttpError as e:
        log.warning("Kunde inte sätta thumbnail (kräver verifierad kanal): %s", e)
        return False


def set_visibility(settings: Settings, video_id: str, publish_at: str | None = None) -> None:
    """Make a video public now, or schedule it (publish_at = ISO 8601 UTC, e.g. 2026-10-12T16:00:00Z)."""
    yt = youtube_client(settings)
    items = yt.videos().list(part="status", id=video_id).execute().get("items", [])
    if not items:
        raise ValueError(f"Hittar ingen video med id {video_id}")
    status = items[0]["status"]
    keep = {k: status[k] for k in ("selfDeclaredMadeForKids", "containsSyntheticMedia", "license", "embeddable",
                                   "publicStatsViewable") if k in status}
    if publish_at:
        new_status = {**keep, "privacyStatus": "private", "publishAt": publish_at}
    else:
        new_status = {**keep, "privacyStatus": "public"}
    yt.videos().update(part="status", body={"id": video_id, "status": new_status}).execute()
