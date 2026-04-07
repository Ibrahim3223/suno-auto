"""YouTube Data API v3 uploader with OAuth2 token refresh support."""

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from src.config import setup_logging

logger = logging.getLogger(__name__)

YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
UPLOAD_CHUNK_SIZE = 50 * 1024 * 1024  # 50 MB resumable chunks
MAX_RETRIES = 5


def _load_credentials() -> Credentials:
    """Load and refresh YouTube OAuth2 credentials from environment variables.

    Reads YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, and YOUTUBE_OAUTH_TOKEN
    from environment. Refreshes the access token if expired.

    Returns:
        Valid google.oauth2.credentials.Credentials object.

    Raises:
        EnvironmentError: If required environment variables are missing.
        ValueError: If the token JSON is invalid.
    """
    client_id = os.environ.get("YOUTUBE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET", "").strip()
    token_json = os.environ.get("YOUTUBE_OAUTH_TOKEN", "").strip()

    if not client_id:
        raise EnvironmentError("YOUTUBE_CLIENT_ID environment variable is not set")
    if not client_secret:
        raise EnvironmentError("YOUTUBE_CLIENT_SECRET environment variable is not set")
    if not token_json:
        raise EnvironmentError(
            "YOUTUBE_OAUTH_TOKEN environment variable is not set. "
            "Run: python scripts/setup_youtube_oauth.py --client-id ID --client-secret SECRET"
        )

    try:
        token_data: dict[str, Any] = json.loads(token_json)
    except json.JSONDecodeError as e:
        raise ValueError(f"YOUTUBE_OAUTH_TOKEN is not valid JSON: {e}") from e

    creds = Credentials(
        token=token_data.get("token") or token_data.get("access_token"),
        refresh_token=token_data.get("refresh_token"),
        token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=client_id,
        client_secret=client_secret,
        scopes=YOUTUBE_SCOPES,
    )

    # Refresh if expired or about to expire
    if not creds.valid:
        logger.info("Access token expired — refreshing via refresh_token...")
        creds.refresh(Request())
        logger.info("Token refreshed successfully. New access token obtained.")
        logger.info(
            "If this is a GitHub Actions run, update YOUTUBE_OAUTH_TOKEN secret with: %s",
            json.dumps({
                "token": creds.token,
                "refresh_token": creds.refresh_token,
                "token_uri": creds.token_uri,
            }),
        )

    return creds


def upload_video(
    video_path: Path,
    title: str,
    description: str,
    tags: list[str],
    category_id: str = "10",
    privacy_status: str = "public",
    thumbnail_path: Path | None = None,
) -> str:
    """Upload a video to YouTube using resumable upload.

    Args:
        video_path: Path to the MP4 video file.
        title: YouTube video title.
        description: YouTube video description.
        tags: List of tag strings.
        category_id: YouTube category ID ("10" = Music).
        privacy_status: "public", "unlisted", or "private".
        thumbnail_path: Optional path to the thumbnail PNG.

    Returns:
        YouTube video ID string (e.g. "dQw4w9WgXcQ").

    Raises:
        RuntimeError: If the upload fails after all retries.
    """
    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    creds = _load_credentials()
    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": title[:100],           # YouTube limit
            "description": description[:5000],  # YouTube limit
            "tags": tags[:500],             # YouTube limit
            "categoryId": category_id,
            "defaultLanguage": "en",
            "defaultAudioLanguage": "en",
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        resumable=True,
        chunksize=UPLOAD_CHUNK_SIZE,
    )

    logger.info(
        "Starting YouTube upload: '%s' (%.1f MB, %s)",
        title[:60], video_path.stat().st_size / 1e6, privacy_status,
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    video_id = _execute_resumable_upload(request)
    logger.info("Upload complete. Video ID: %s", video_id)
    logger.info("Video URL: https://www.youtube.com/watch?v=%s", video_id)

    # Upload thumbnail if provided
    if thumbnail_path and thumbnail_path.exists():
        _upload_thumbnail(youtube, video_id, thumbnail_path)

    return video_id


def _execute_resumable_upload(request: Any) -> str:
    """Drive a resumable MediaFileUpload to completion with exponential backoff.

    Args:
        request: googleapiclient upload request object.

    Returns:
        YouTube video ID string.
    """
    response = None
    error = None
    retry = 0

    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                pct = int(status.progress() * 100)
                logger.info("Upload progress: %d%%", pct)
        except HttpError as e:
            if e.resp.status in (500, 502, 503, 504):
                error = e
                retry += 1
                if retry > MAX_RETRIES:
                    raise RuntimeError(
                        f"YouTube upload failed after {MAX_RETRIES} retries: {e}"
                    ) from e
                wait = 2 ** retry
                logger.warning("HTTP %d error — retrying in %ds (attempt %d/%d)", e.resp.status, wait, retry, MAX_RETRIES)
                time.sleep(wait)
            else:
                raise RuntimeError(f"YouTube upload failed with unrecoverable error: {e}") from e

    if response is None:
        raise RuntimeError("Upload completed but response is None")

    return response["id"]


def _upload_thumbnail(youtube: Any, video_id: str, thumbnail_path: Path) -> None:
    """Upload a custom thumbnail for a video.

    Args:
        youtube: Authenticated YouTube API client.
        video_id: YouTube video ID.
        thumbnail_path: Path to the thumbnail image (PNG/JPG).
    """
    logger.info("Uploading thumbnail: %s", thumbnail_path.name)
    try:
        youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(str(thumbnail_path)),
        ).execute()
        logger.info("Thumbnail uploaded successfully")
    except HttpError as e:
        # Thumbnail upload failure is non-fatal
        logger.warning("Thumbnail upload failed (non-fatal): %s", e)


if __name__ == "__main__":
    import sys
    setup_logging()

    if len(sys.argv) < 3:
        print("Usage: python -m src.youtube_uploader <video.mp4> <title>")
        sys.exit(1)

    vpath = Path(sys.argv[1])
    vtitle = sys.argv[2]
    vid = upload_video(
        video_path=vpath,
        title=vtitle,
        description="Test upload from lo-fi pipeline",
        tags=["lofi", "test"],
        privacy_status="private",
    )
    print(f"Uploaded: https://www.youtube.com/watch?v={vid}")
