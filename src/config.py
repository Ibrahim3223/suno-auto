"""Config loader and validator for the lo-fi pipeline."""

import logging
import os
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Paths relative to project root
PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
CONFIG_YAML = CONFIG_DIR / "config.yaml"
PROMPTS_YAML = CONFIG_DIR / "prompts.yaml"

OUTPUT_DIR = PROJECT_ROOT / "output"
MUSIC_DIR = OUTPUT_DIR / "music"
IMAGES_DIR = OUTPUT_DIR / "images"
VIDEOS_DIR = OUTPUT_DIR / "videos"
TEMP_DIR = OUTPUT_DIR / "temp"


def load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file and return its contents as a dict."""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_config() -> dict[str, Any]:
    """Load and validate the main config.yaml."""
    logger.info("Loading config from %s", CONFIG_YAML)
    config = load_yaml(CONFIG_YAML)
    _validate_config(config)
    return config


def load_prompts() -> dict[str, Any]:
    """Load prompts.yaml."""
    logger.info("Loading prompts from %s", PROMPTS_YAML)
    return load_yaml(PROMPTS_YAML)


def _validate_config(config: dict[str, Any]) -> None:
    """Validate required config keys and values."""
    required_sections = ["channel", "music", "image", "video", "youtube", "schedule"]
    for section in required_sections:
        if section not in config:
            raise ValueError(f"Missing required config section: '{section}'")

    music = config["music"]
    if music.get("tracks_per_mix", 0) < 2:
        raise ValueError("music.tracks_per_mix must be >= 2")
    if music.get("target_mix_duration", 0) <= 0:
        raise ValueError("music.target_mix_duration must be > 0")

    image = config["image"]
    if image.get("width", 0) <= 0 or image.get("height", 0) <= 0:
        raise ValueError("image width and height must be > 0")

    logger.info("Config validation passed")


def ensure_output_dirs() -> None:
    """Create all output directories if they don't exist."""
    for d in [MUSIC_DIR, IMAGES_DIR, VIDEOS_DIR, TEMP_DIR]:
        d.mkdir(parents=True, exist_ok=True)
        logger.debug("Ensured directory: %s", d)


def setup_logging(level: int = logging.INFO) -> None:
    """Configure root logger with a standard format."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


if __name__ == "__main__":
    setup_logging()
    cfg = load_config()
    prompts = load_prompts()
    print("Config loaded OK:")
    import json
    print(json.dumps(cfg, indent=2, default=str))
    print("\nPrompts loaded OK — keys:", list(prompts.keys()))
