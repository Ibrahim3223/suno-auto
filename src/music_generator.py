"""Suno AI music generator — unofficial cookie-based HTTP API."""

import logging
import os
import random
import time
from pathlib import Path

import requests

from src.config import MUSIC_DIR, load_config, load_prompts, setup_logging

logger = logging.getLogger(__name__)

SUNO_BASE_URL = "https://studio-api.suno.ai"
GENERATE_ENDPOINT = f"{SUNO_BASE_URL}/api/generate/v2/"
FEED_ENDPOINT = f"{SUNO_BASE_URL}/api/feed/"

POLL_INTERVAL_SEC = 10
POLL_MAX_SEC = 300       # 5 dakika
REQUEST_DELAY_SEC = 5    # Rate limit
MAX_RETRIES = 3


def _get_cookie() -> str:
    """Read Suno session cookie from environment variable."""
    cookie = os.environ.get("SUNO_COOKIE", "").strip()
    if not cookie:
        raise EnvironmentError(
            "SUNO_COOKIE environment variable is not set. "
            "Log in to suno.com, open DevTools → Network, copy the Cookie header."
        )
    return cookie


def _headers(cookie: str) -> dict[str, str]:
    """Build request headers with the Suno cookie."""
    return {
        "Cookie": cookie,
        "Content-Type": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Referer": "https://suno.com/",
        "Origin": "https://suno.com",
    }


def _build_prompt(config: dict, prompts: dict) -> str:
    """Combine style prompt from config with a random mood from prompts.yaml."""
    style = config["music"]["style_prompt"]
    mood = random.choice(prompts["music_moods"])
    return f"{style}, {mood}"


def _generate_pair(cookie: str, prompt: str, config: dict) -> list[str]:
    """Send one generation request to Suno and return the 2 clip IDs."""
    payload = {
        "prompt": "",
        "gpt_description_prompt": prompt,
        "mv": "chirp-v4",
        "make_instrumental": config["music"]["make_instrumental"],
    }
    response = requests.post(
        GENERATE_ENDPOINT,
        json=payload,
        headers=_headers(cookie),
        timeout=60,
    )
    if response.status_code == 401:
        raise PermissionError(
            "Suno returned 401 Unauthorized — your SUNO_COOKIE has expired. "
            "Log in to suno.com, copy a fresh Cookie header, and update the secret."
        )
    response.raise_for_status()
    data = response.json()

    clips = data.get("clips", [])
    if not clips:
        # Some API versions nest differently
        clips = data if isinstance(data, list) else []
    if len(clips) < 2:
        raise ValueError(f"Expected 2 clips from Suno, got {len(clips)}. Response: {data}")

    return [clip["id"] for clip in clips[:2]]


def _poll_until_complete(cookie: str, clip_ids: list[str]) -> list[dict]:
    """Poll feed endpoint until all clips are complete or timeout."""
    ids_param = ",".join(clip_ids)
    deadline = time.time() + POLL_MAX_SEC
    logger.info("Polling for clip IDs: %s", ids_param)

    while time.time() < deadline:
        response = requests.get(
            FEED_ENDPOINT,
            params={"ids": ids_param},
            headers=_headers(cookie),
            timeout=30,
        )
        response.raise_for_status()
        clips = response.json()

        statuses = {c["id"]: c.get("status", "unknown") for c in clips}
        logger.debug("Clip statuses: %s", statuses)

        complete = [c for c in clips if c.get("status") == "complete"]
        if len(complete) == len(clip_ids):
            logger.info("All clips complete")
            return complete

        failed = [c for c in clips if c.get("status") in ("error", "failed")]
        if failed:
            raise RuntimeError(f"Suno clip generation failed: {failed}")

        logger.debug("Waiting %ds before next poll...", POLL_INTERVAL_SEC)
        time.sleep(POLL_INTERVAL_SEC)

    raise TimeoutError(
        f"Suno clips did not complete within {POLL_MAX_SEC}s. IDs: {clip_ids}"
    )


def _download_track(audio_url: str, output_path: Path) -> None:
    """Stream-download an audio file to disk."""
    logger.info("Downloading %s → %s", audio_url, output_path)
    with requests.get(audio_url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
    logger.info("Downloaded %s (%.1f MB)", output_path.name, output_path.stat().st_size / 1e6)


def generate_tracks(count: int) -> list[Path]:
    """Generate `count` lo-fi tracks via Suno API and save them to output/music/.

    Returns a list of Paths to the downloaded MP3 files.
    Each Suno request yields 2 tracks, so `count/2` requests are made
    (rounded up). Excess tracks are discarded.

    Args:
        count: Number of tracks to generate.

    Returns:
        List of Paths to downloaded MP3 files.
    """
    config = load_config()
    prompts = load_prompts()
    cookie = _get_cookie()

    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    tracks: list[Path] = []
    track_index = 1
    requests_needed = (count + 1) // 2  # ceiling division

    logger.info("Generating %d tracks (%d Suno requests)...", count, requests_needed)

    for req_num in range(requests_needed):
        if len(tracks) >= count:
            break

        prompt = _build_prompt(config, prompts)
        logger.info("[Request %d/%d] Prompt: %s", req_num + 1, requests_needed, prompt)

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                clip_ids = _generate_pair(cookie, prompt, config)
                logger.info("Clip IDs: %s", clip_ids)
                completed_clips = _poll_until_complete(cookie, clip_ids)

                for clip in completed_clips:
                    if len(tracks) >= count:
                        break
                    audio_url = clip.get("audio_url", "")
                    if not audio_url:
                        logger.warning("Clip %s has no audio_url, skipping", clip.get("id"))
                        continue

                    output_path = MUSIC_DIR / f"track_{track_index:03d}.mp3"
                    _download_track(audio_url, output_path)
                    tracks.append(output_path)
                    track_index += 1

                break  # success — exit retry loop

            except (PermissionError, TimeoutError) as e:
                # Don't retry auth or timeout errors
                raise
            except Exception as e:
                logger.warning(
                    "Attempt %d/%d failed for request %d: %s",
                    attempt, MAX_RETRIES, req_num + 1, e,
                )
                if attempt == MAX_RETRIES:
                    raise RuntimeError(
                        f"Suno request {req_num + 1} failed after {MAX_RETRIES} retries"
                    ) from e
                time.sleep(REQUEST_DELAY_SEC * attempt)

        # Rate-limit delay between requests (skip after last)
        if req_num < requests_needed - 1:
            logger.debug("Rate limit delay: %ds", REQUEST_DELAY_SEC)
            time.sleep(REQUEST_DELAY_SEC)

    logger.info("Generated %d tracks: %s", len(tracks), [str(p) for p in tracks])
    return tracks


if __name__ == "__main__":
    setup_logging()
    tracks = generate_tracks(count=2)
    print(f"Generated tracks: {tracks}")
