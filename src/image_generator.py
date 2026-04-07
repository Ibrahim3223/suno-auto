"""Replicate Flux 1.1 Pro image generator for lo-fi backgrounds."""

import logging
import os
import random
import time
from pathlib import Path

import replicate
import requests

from src.config import IMAGES_DIR, load_config, load_prompts, setup_logging

logger = logging.getLogger(__name__)

IMAGE_TIMEOUT_SEC = 300  # 5 minutes


def generate_image(prompt: str | None = None) -> Path:
    """Generate a single 1920x1080 lo-fi background image via Replicate Flux 1.1 Pro.

    If `prompt` is None, a random prompt from prompts.yaml is used.

    Args:
        prompt: Image generation prompt. If None, picks a random one from config.

    Returns:
        Path to the saved PNG file.
    """
    token = os.environ.get("REPLICATE_API_TOKEN", "").strip()
    if not token:
        raise EnvironmentError(
            "REPLICATE_API_TOKEN environment variable is not set. "
            "Get your token from replicate.com → Settings → API Tokens."
        )
    os.environ["REPLICATE_API_TOKEN"] = token

    config = load_config()
    prompts_data = load_prompts()
    image_cfg = config["image"]

    if prompt is None:
        prompt = random.choice(prompts_data["image_prompts"])
        logger.info("Using random image prompt: %.80s...", prompt)
    else:
        logger.info("Using provided image prompt: %.80s...", prompt)

    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = int(time.time())
    output_path = IMAGES_DIR / f"background_{timestamp}.png"

    logger.info(
        "Calling Replicate %s (%dx%d, steps=%d)...",
        image_cfg["model"], image_cfg["width"], image_cfg["height"],
        image_cfg["num_inference_steps"],
    )

    start = time.time()
    try:
        output = replicate.run(
            image_cfg["model"],
            input={
                "prompt": prompt,
                "width": image_cfg["width"],
                "height": image_cfg["height"],
                "num_inference_steps": image_cfg["num_inference_steps"],
                "guidance_scale": image_cfg["guidance_scale"],
                "output_format": "png",
                "output_quality": 95,
            },
        )
    except Exception as e:
        elapsed = time.time() - start
        if elapsed >= IMAGE_TIMEOUT_SEC:
            raise TimeoutError(
                f"Replicate image generation timed out after {elapsed:.0f}s"
            ) from e
        raise RuntimeError(f"Replicate API error: {e}") from e

    elapsed = time.time() - start
    if elapsed >= IMAGE_TIMEOUT_SEC:
        raise TimeoutError(
            f"Replicate image generation timed out after {elapsed:.0f}s"
        )

    # output is typically a URL string or a list
    image_url = output[0] if isinstance(output, list) else output
    if hasattr(image_url, "url"):
        image_url = image_url.url
    image_url = str(image_url)

    logger.info("Image generated in %.1fs, downloading from Replicate CDN...", elapsed)
    _download_image(image_url, output_path)

    logger.info(
        "Image saved: %s (%.2f MB)", output_path.name, output_path.stat().st_size / 1e6
    )
    return output_path


def _download_image(url: str, output_path: Path) -> None:
    """Download an image from a URL to disk.

    Args:
        url: Source URL.
        output_path: Destination file path.
    """
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)


if __name__ == "__main__":
    import sys
    setup_logging()
    custom_prompt = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else None
    path = generate_image(prompt=custom_prompt)
    print(f"Image saved to: {path}")
