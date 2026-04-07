"""FFmpeg-based audio processing: normalization, crossfade concatenation, timestamps."""

import logging
import subprocess
from pathlib import Path

from src.config import TEMP_DIR, setup_logging

logger = logging.getLogger(__name__)


def get_duration(filepath: Path) -> float:
    """Return the duration of an audio/video file in seconds using ffprobe.

    Args:
        filepath: Path to the media file.

    Returns:
        Duration in seconds as a float.
    """
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(filepath),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffprobe failed on {filepath}: {result.stderr.strip()}"
        )
    return float(result.stdout.strip())


def format_timestamp(seconds: float) -> str:
    """Format seconds into M:SS or H:MM:SS string.

    Args:
        seconds: Total seconds.

    Returns:
        Human-readable timestamp string.
    """
    total = int(seconds)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def normalize_audio(input_path: Path, output_path: Path) -> None:
    """Normalize audio using the FFmpeg loudnorm filter (EBU R128).

    Args:
        input_path: Source audio file.
        output_path: Destination path for normalized audio.
    """
    logger.info("Normalizing %s → %s", input_path.name, output_path.name)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-af", "loudnorm=I=-14:LRA=11:TP=-1",
        "-ar", "44100",
        "-c:a", "libmp3lame", "-q:a", "2",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(
            f"Audio normalization failed for {input_path.name}:\n{result.stderr[-1000:]}"
        )
    logger.debug("Normalized: %s", output_path.name)


def concatenate_with_crossfade(
    tracks: list[Path],
    output_path: Path,
    crossfade_sec: int = 3,
    target_duration: int = 3600,
) -> tuple[Path, list[tuple[str, str]]]:
    """Concatenate audio tracks with acrossfade, trimming/fading to target duration.

    Args:
        tracks: Ordered list of audio file paths.
        output_path: Destination for the final mix MP3.
        crossfade_sec: Duration of the crossfade between tracks in seconds.
        target_duration: Target total duration in seconds (default 3600 = 1 hour).

    Returns:
        Tuple of (output_path, timestamps) where timestamps is a list of
        (time_str, label) tuples, e.g. [("0:00", "Track 1"), ("3:15", "Track 2")].
    """
    if not tracks:
        raise ValueError("No tracks provided for concatenation")

    TEMP_DIR.mkdir(parents=True, exist_ok=True)

    # Step 1: Normalize all tracks
    normalized: list[Path] = []
    for i, track in enumerate(tracks):
        norm_path = TEMP_DIR / f"norm_{i:03d}.mp3"
        normalize_audio(track, norm_path)
        normalized.append(norm_path)

    # Step 2: Build timestamps and determine which tracks we need
    timestamps: list[tuple[str, str]] = []
    cursor = 0.0
    selected: list[Path] = []

    for i, norm in enumerate(normalized):
        if cursor >= target_duration:
            break
        duration = get_duration(norm)
        timestamps.append((format_timestamp(cursor), f"Track {i + 1}"))
        selected.append(norm)
        # After crossfade, effective duration is (duration - crossfade_sec)
        cursor += duration - crossfade_sec

    if not selected:
        raise RuntimeError("No tracks selected — check track durations and target_duration")

    logger.info(
        "Concatenating %d tracks (target: %ds, timestamps: %d)",
        len(selected), target_duration, len(timestamps),
    )

    # Step 3: Iteratively crossfade tracks using acrossfade
    current = selected[0]

    for i in range(1, len(selected)):
        next_track = selected[i]
        merged = TEMP_DIR / f"merged_{i:03d}.mp3"

        cmd = [
            "ffmpeg", "-y",
            "-i", str(current),
            "-i", str(next_track),
            "-filter_complex",
            f"[0][1]acrossfade=d={crossfade_sec}:c1=tri:c2=tri[out]",
            "-map", "[out]",
            "-c:a", "libmp3lame", "-q:a", "2",
            str(merged),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise RuntimeError(
                f"Crossfade step {i} failed:\n{result.stderr[-1000:]}"
            )
        current = merged
        logger.debug("Crossfaded up to track %d", i + 1)

    # Step 4: Trim to target_duration with fade-out on the last 10 seconds
    actual_duration = get_duration(current)
    fade_out_start = max(0.0, target_duration - 10)

    if actual_duration > target_duration:
        logger.info(
            "Mix duration %.1fs > target %ds — trimming with fade-out", actual_duration, target_duration
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", str(current),
            "-af",
            f"afade=t=out:st={fade_out_start}:d=10",
            "-t", str(target_duration),
            "-c:a", "libmp3lame", "-q:a", "2",
            str(output_path),
        ]
    else:
        logger.info(
            "Mix duration %.1fs <= target %ds — no trimming needed", actual_duration, target_duration
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", str(current),
            "-c:a", "libmp3lame", "-q:a", "2",
            str(output_path),
        ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(
            f"Final mix trim/export failed:\n{result.stderr[-1000:]}"
        )

    final_duration = get_duration(output_path)
    logger.info(
        "Mix complete: %s (%.1f min, %d timestamps)",
        output_path.name, final_duration / 60, len(timestamps),
    )
    return output_path, timestamps


if __name__ == "__main__":
    import sys
    setup_logging()

    if len(sys.argv) < 3:
        print("Usage: python -m src.audio_processor <track1.mp3> <track2.mp3> ...")
        print("       Concatenates tracks and writes mix.mp3")
        sys.exit(1)

    input_tracks = [Path(p) for p in sys.argv[1:]]
    out = Path("output/temp/test_mix.mp3")
    out.parent.mkdir(parents=True, exist_ok=True)

    result_path, ts = concatenate_with_crossfade(input_tracks, out, crossfade_sec=3, target_duration=3600)
    print(f"Mix saved to: {result_path}")
    print("Timestamps:")
    for t, label in ts:
        print(f"  {t}  {label}")
