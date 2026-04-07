"""Main pipeline orchestrator — runs the full lo-fi video generation and upload flow."""

import json
import logging
import shutil
import time
from pathlib import Path

from src.audio_processor import concatenate_with_crossfade
from src.config import (
    IMAGES_DIR,
    MUSIC_DIR,
    TEMP_DIR,
    VIDEOS_DIR,
    ensure_output_dirs,
    load_config,
    setup_logging,
)
from src.image_generator import generate_image
from src.metadata_generator import generate_metadata
from src.music_generator import generate_tracks
from src.video_assembler import assemble_video, create_thumbnail
from src.youtube_uploader import upload_video

logger = logging.getLogger(__name__)


def _step(name: str) -> None:
    """Log a clearly visible pipeline step header."""
    logger.info("=" * 60)
    logger.info("STEP: %s", name)
    logger.info("=" * 60)


def _cleanup_temp_files() -> None:
    """Remove temporary files to free disk space on GitHub Actions runners."""
    for d in [MUSIC_DIR, TEMP_DIR, IMAGES_DIR]:
        if d.exists():
            shutil.rmtree(d)
            logger.info("Cleaned up: %s", d)
    # Re-create empty dirs so the repo structure is intact
    for d in [MUSIC_DIR, TEMP_DIR, IMAGES_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def run_pipeline() -> None:
    """Execute the full lo-fi video pipeline end-to-end.

    Steps:
        1. Load and validate config
        2. Ensure output directories exist
        3. Generate music tracks via Suno API
        4. Mix tracks with crossfade via FFmpeg
        5. Generate background image via Replicate Flux
        6. Assemble video via FFmpeg (Ken Burns + visualizer + color grade)
        7. Create YouTube thumbnail
        8. Generate video metadata (title, description, tags)
        9. Upload to YouTube
        10. Cleanup temp files
        11. Log summary

    Raises:
        Exception: Re-raises any unhandled exception after logging the failed step.
    """
    pipeline_start = time.time()
    setup_logging()

    logger.info("╔══════════════════════════════════════╗")
    logger.info("║   CHILL DRIFT — Lo-Fi Pipeline Start  ║")
    logger.info("╚══════════════════════════════════════╝")

    # ── Step 1: Config ─────────────────────────────────────────
    _step("1 — Load config")
    config = load_config()
    ensure_output_dirs()

    music_cfg = config["music"]
    tracks_count: int = music_cfg["tracks_per_mix"]
    crossfade_sec: int = music_cfg["crossfade_duration"]
    target_duration: int = music_cfg["target_mix_duration"]
    run_ts = int(pipeline_start)  # unique timestamp for this run

    # ── Step 2: Music generation ───────────────────────────────
    _step("2 — Generate music tracks (Suno API)")
    t0 = time.time()
    try:
        tracks = generate_tracks(count=tracks_count)
        logger.info("Music generation done in %.1fs — %d tracks", time.time() - t0, len(tracks))
    except Exception:
        logger.exception("FATAL: Music generation failed — aborting pipeline")
        raise

    # ── Step 3: Audio mixing ───────────────────────────────────
    _step("3 — Mix audio with crossfade (FFmpeg)")
    t0 = time.time()
    mix_path = TEMP_DIR / f"mix_{run_ts}.mp3"
    try:
        mix_path, timestamps = concatenate_with_crossfade(
            tracks=tracks,
            output_path=mix_path,
            crossfade_sec=crossfade_sec,
            target_duration=target_duration,
        )
        logger.info("Audio mixing done in %.1fs — %d timestamps", time.time() - t0, len(timestamps))
    except Exception:
        logger.exception("FATAL: Audio mixing failed — aborting pipeline")
        raise

    # ── Step 4: Image generation ───────────────────────────────
    _step("4 — Generate background image (Replicate Flux)")
    t0 = time.time()
    try:
        image_path = generate_image()
        logger.info("Image generation done in %.1fs — %s", time.time() - t0, image_path.name)
    except Exception:
        logger.exception("FATAL: Image generation failed — aborting pipeline")
        raise

    # ── Step 5: Video assembly ─────────────────────────────────
    _step("5 — Assemble video (FFmpeg)")
    t0 = time.time()
    video_path = VIDEOS_DIR / f"lofi_{run_ts}.mp4"
    try:
        assemble_video(
            image_path=image_path,
            audio_path=mix_path,
            output_path=video_path,
            config=config,
        )
        logger.info(
            "Video assembly done in %.1fs — %.1f MB",
            time.time() - t0, video_path.stat().st_size / 1e6,
        )
    except Exception:
        logger.exception("FATAL: Video assembly failed — aborting pipeline")
        raise

    # ── Step 6: Metadata ───────────────────────────────────────
    _step("6 — Generate metadata")
    metadata = generate_metadata(timestamps)
    logger.info("Title: %s", metadata["title"])

    # ── Step 7: Thumbnail ──────────────────────────────────────
    _step("7 — Create thumbnail")
    thumb_path: Path | None = VIDEOS_DIR / f"thumb_{run_ts}.png"
    try:
        create_thumbnail(image_path, metadata["title"], thumb_path)
    except Exception as e:
        logger.warning("Thumbnail creation failed (non-fatal): %s", e)
        thumb_path = None

    # ── Step 8: YouTube upload ─────────────────────────────────
    _step("8 — Upload to YouTube")
    t0 = time.time()
    video_id: str | None = None
    try:
        yt_cfg = config["youtube"]
        video_id = upload_video(
            video_path=video_path,
            title=metadata["title"],
            description=metadata["description"],
            tags=metadata["tags"],
            category_id=yt_cfg["category_id"],
            privacy_status=yt_cfg["privacy_status"],
            thumbnail_path=thumb_path,
        )
        logger.info("YouTube upload done in %.1fs — video ID: %s", time.time() - t0, video_id)
    except Exception:
        logger.exception(
            "YouTube upload failed. Video saved locally at %s "
            "(will be included in GitHub Actions artifact).",
            video_path,
        )
        video_id = None  # non-fatal — continue to cleanup and summary

    # ── Step 9: Cleanup ────────────────────────────────────────
    _step("9 — Cleanup temporary files")
    _cleanup_temp_files()

    # ── Step 10: Summary ───────────────────────────────────────
    total_elapsed = time.time() - pipeline_start
    logger.info("╔══════════════════════════════════════╗")
    logger.info("║         PIPELINE COMPLETE              ║")
    logger.info("╠══════════════════════════════════════╣")
    logger.info("║  Total time:  %6.1f minutes          ║", total_elapsed / 60)
    logger.info("║  Video:       %s", video_path.name[:30])
    if video_id:
        logger.info("║  YouTube:     https://youtu.be/%s", video_id)
    else:
        logger.info("║  YouTube:     UPLOAD FAILED — check logs")
    logger.info("╚══════════════════════════════════════╝")

    # Save summary JSON
    summary = {
        "success": video_id is not None,
        "video_id": video_id,
        "video_url": f"https://www.youtube.com/watch?v={video_id}" if video_id else None,
        "title": metadata["title"],
        "video_path": str(video_path),
        "total_duration_sec": total_elapsed,
        "run_timestamp": run_ts,
    }
    summary_path = VIDEOS_DIR / f"summary_{run_ts}.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    logger.info("Summary saved to %s", summary_path)


if __name__ == "__main__":
    run_pipeline()
