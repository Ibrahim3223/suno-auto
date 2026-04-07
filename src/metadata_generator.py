"""YouTube metadata generator: title, description, tags from prompts.yaml templates."""

import json
import logging
import random
import time
from pathlib import Path
from typing import Any

from src.config import VIDEOS_DIR, load_prompts, setup_logging

logger = logging.getLogger(__name__)


def _format_timestamps(timestamps: list[tuple[str, str]]) -> str:
    """Format a list of (time, label) tuples into a readable string block.

    Args:
        timestamps: List of (time_str, label) tuples.

    Returns:
        Multi-line string for use in video description.
    """
    if not timestamps:
        return "0:00 Track 1"
    return "\n".join(f"{t}  {label}" for t, label in timestamps)


def generate_metadata(
    timestamps: list[tuple[str, str]],
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Generate YouTube video metadata (title, description, tags).

    Selects random mood, scene, and title template from prompts.yaml.
    Saves the metadata as a timestamped JSON file for debugging.

    Args:
        timestamps: List of (time_str, label) tuples from audio_processor.
        output_dir: Directory to save the metadata JSON. Defaults to output/videos/.

    Returns:
        Dict with keys: title, description, tags.
    """
    if output_dir is None:
        output_dir = VIDEOS_DIR

    prompts = load_prompts()

    mood = random.choice(prompts["moods"])
    scene = random.choice(prompts["scenes"])
    template = random.choice(prompts["title_templates"])

    title = template.format(mood=mood, scene=scene)
    logger.info("Generated title: %s", title)

    timestamp_block = _format_timestamps(timestamps)
    description = prompts["description_template"].format(
        title=title,
        timestamps=timestamp_block,
    )

    tags: list[str] = list(prompts["tags"])

    metadata: dict[str, Any] = {
        "title": title,
        "description": description,
        "tags": tags,
        "mood": mood,
        "scene": scene,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "timestamps": [{"time": t, "label": l} for t, l in timestamps],
    }

    # Save JSON for debugging / artifact upload
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    json_path = output_dir / f"metadata_{ts}.json"
    json_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Metadata saved to %s", json_path)

    return metadata


if __name__ == "__main__":
    setup_logging()
    sample_timestamps = [
        ("0:00", "Track 1"),
        ("3:22", "Track 2"),
        ("6:45", "Track 3"),
    ]
    meta = generate_metadata(sample_timestamps)
    print("Title:", meta["title"])
    print("\nDescription:\n", meta["description"])
    print("\nTags:", meta["tags"])
