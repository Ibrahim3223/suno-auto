"""FFmpeg video assembler: Ken Burns effect, audio visualizer, color grading."""

import logging
import subprocess
from pathlib import Path
from typing import Any

from src.config import TEMP_DIR, VIDEOS_DIR, setup_logging

logger = logging.getLogger(__name__)


def assemble_video(
    image_path: Path,
    audio_path: Path,
    output_path: Path,
    config: dict[str, Any],
) -> Path:
    """Assemble the final lo-fi video from a background image and audio mix.

    Uses a complex FFmpeg filter chain:
      1. Ken Burns slow zoom (zoompan)
      2. Audio visualizer (showwaves, bottom bar)
      3. Color grading (eq + vignette)

    Falls back to a simpler encoding if the complex filter fails.

    Args:
        image_path: Path to the background PNG (1920x1080).
        audio_path: Path to the audio mix MP3.
        output_path: Destination MP4 path.
        config: Loaded config dict.

    Returns:
        Path to the assembled MP4 file.
    """
    video_cfg = config["video"]
    dur = config["music"]["target_mix_duration"]

    fps = video_cfg["fps"]
    crf = video_cfg["crf"]
    preset = video_cfg["preset"]

    ken = video_cfg["ken_burns"]
    viz = video_cfg["visualizer"]
    grade = video_cfg["color_grade"]

    # zoompan duration in frames
    zoom_frames = dur * fps

    # Build complex filter if all effects are enabled
    if ken["enabled"] and viz["enabled"] and grade.get("vignette", False):
        success = _assemble_full(
            image_path, audio_path, output_path,
            dur, fps, crf, preset,
            zoom_frames, ken, viz, grade,
        )
        if not success:
            logger.warning("Full filter chain failed — falling back to simplified encoding")
            success = _assemble_simple(image_path, audio_path, output_path, dur, fps, crf)
            if not success:
                raise RuntimeError("Both full and fallback FFmpeg encoding failed")
    else:
        success = _assemble_simple(image_path, audio_path, output_path, dur, fps, crf)
        if not success:
            raise RuntimeError("Simplified FFmpeg encoding failed")

    logger.info("Video assembled: %s", output_path)
    return output_path


def _build_filter_complex(
    zoom_frames: int,
    ken: dict,
    viz: dict,
    grade: dict,
    fps: int,
) -> str:
    """Build the FFmpeg -filter_complex string.

    Args:
        zoom_frames: Total number of frames for the zoompan effect.
        ken: Ken Burns config dict.
        viz: Visualizer config dict.
        grade: Color grade config dict.
        fps: Frames per second.

    Returns:
        Filter complex string.
    """
    zoom_end = ken["zoom_end"]
    zoom_rate = (zoom_end - 1.0) / zoom_frames if zoom_frames > 0 else 0.0003
    zoom_expr = f"min(1+{zoom_rate:.6f}*in,{zoom_end})"

    viz_h = viz["height"]
    viz_color = viz["bar_color"]
    viz_mode = viz["mode"]
    viz_opacity = viz["opacity"]
    contrast = grade["contrast"]
    saturation = grade["saturation"]
    brightness = grade.get("warmth", 0.0)

    filter_complex = (
        f"[0:v]zoompan="
        f"z='{zoom_expr}':"
        f"x='iw/2-(iw/zoom/2)':"
        f"y='ih/2-(ih/zoom/2)':"
        f"d={zoom_frames}:"
        f"s=1920x1080:"
        f"fps={fps}[bg];"

        f"[1:a]showwaves="
        f"s=1920x{viz_h}:"
        f"mode={viz_mode}:"
        f"rate={fps}:"
        f"colors={viz_color}[waves];"

        f"[waves]format=rgba,"
        f"colorchannelmixer=aa={viz_opacity}[waves_alpha];"

        f"[bg][waves_alpha]overlay=0:H-{viz_h}:format=auto[overlaid];"

        f"[overlaid]"
        f"eq=contrast={contrast}:saturation={saturation}:brightness={brightness},"
        f"vignette=PI/5[out]"
    )
    return filter_complex


def _assemble_full(
    image_path: Path,
    audio_path: Path,
    output_path: Path,
    dur: int,
    fps: int,
    crf: int,
    preset: str,
    zoom_frames: int,
    ken: dict,
    viz: dict,
    grade: dict,
) -> bool:
    """Run FFmpeg with the full complex filter chain.

    Returns:
        True if encoding succeeded, False otherwise.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    filter_complex = _build_filter_complex(zoom_frames, ken, viz, grade, fps)

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(image_path),
        "-i", str(audio_path),
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-map", "1:a",
        "-c:v", "libx264",
        "-preset", preset,
        "-crf", str(crf),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "44100",
        "-t", str(dur),
        "-shortest",
        str(output_path),
    ]

    logger.info("Running full FFmpeg pipeline (this may take 30-60 min)...")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)

    if result.returncode != 0:
        logger.error("Full FFmpeg failed:\n%s", result.stderr[-2000:])
        return False

    logger.info("Full FFmpeg encoding complete")
    return True


def _assemble_simple(
    image_path: Path,
    audio_path: Path,
    output_path: Path,
    dur: int,
    fps: int,
    crf: int = 22,
) -> bool:
    """Simplified FFmpeg fallback: Ken Burns only, no visualizer or color grade.

    Returns:
        True if encoding succeeded, False otherwise.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    zoom_frames = dur * fps

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(image_path),
        "-i", str(audio_path),
        "-vf",
        f"scale=1920:1080,"
        f"zoompan=z='min(1+0.0002*in,1.1)':d={zoom_frames}:s=1920x1080:fps={fps}",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", str(crf),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-t", str(dur),
        "-shortest",
        str(output_path),
    ]

    logger.info("Running simplified FFmpeg fallback...")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)

    if result.returncode != 0:
        logger.error("Simplified FFmpeg also failed:\n%s", result.stderr[-2000:])
        return False

    logger.info("Simplified FFmpeg encoding complete")
    return True


def create_thumbnail(
    image_path: Path,
    title_text: str,
    output_path: Path,
) -> Path:
    """Create a YouTube thumbnail by overlaying title text on the background image.

    Args:
        image_path: Source background PNG.
        title_text: Text to overlay (up to ~50 chars for readability).
        output_path: Destination PNG path.

    Returns:
        Path to the thumbnail PNG.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Escape special FFmpeg drawtext characters
    safe_text = (
        title_text
        .replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace(":", "\\:")
        .replace("%", "\\%")
    )

    # Two-line thumbnail: channel name + video title
    cmd = [
        "ffmpeg", "-y",
        "-i", str(image_path),
        "-vf",
        (
            "scale=1920:1080,"
            # Dark gradient overlay at bottom for text readability
            "drawbox=x=0:y=850:w=iw:h=230:color=black@0.55:t=fill,"
            # Channel name
            "drawtext=text='CHILL DRIFT':"
            "fontsize=48:fontcolor=white@0.9:"
            "x=(w-text_w)/2:y=875:"
            "shadowcolor=black@0.7:shadowx=2:shadowy=2,"
            # Video title (may be long — split at | if needed)
            f"drawtext=text='{safe_text[:60]}':"
            "fontsize=36:fontcolor=0xE8A87C:"
            "x=(w-text_w)/2:y=940:"
            "shadowcolor=black@0.7:shadowx=2:shadowy=2"
        ),
        "-vframes", "1",
        str(output_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"Thumbnail creation failed:\n{result.stderr[-500:]}")

    logger.info("Thumbnail created: %s", output_path.name)
    return output_path


if __name__ == "__main__":
    import sys
    from src.config import load_config, setup_logging

    setup_logging()
    cfg = load_config()

    if len(sys.argv) < 3:
        print("Usage: python -m src.video_assembler <image.png> <audio.mp3>")
        sys.exit(1)

    img = Path(sys.argv[1])
    audio = Path(sys.argv[2])
    import time as _time
    ts = int(_time.time())
    out = VIDEOS_DIR / f"video_{ts}.mp4"
    thumb = VIDEOS_DIR / f"thumb_{ts}.png"

    assemble_video(img, audio, out, cfg)
    create_thumbnail(img, "Lo-Fi Beats | Chill Drift", thumb)
    print(f"Video: {out}")
    print(f"Thumbnail: {thumb}")
