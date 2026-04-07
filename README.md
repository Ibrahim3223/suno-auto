# Chill Drift — Lo-Fi YouTube Automation Pipeline

Automated daily YouTube lo-fi music video generator. Runs on GitHub Actions, producing one 1-hour lo-fi mix video per day and uploading it to the **Chill Drift** channel.

---

## What It Does

1. Generates ~18 instrumental lo-fi tracks via **Suno AI** (unofficial cookie API)
2. Mixes them into a 1-hour MP3 with crossfade via **FFmpeg**
3. Generates a 1920×1080 anime-style background image via **Replicate Flux 1.1 Pro**
4. Assembles an MP4 with **Ken Burns zoom + audio visualizer + color grading** via FFmpeg
5. Creates a YouTube thumbnail
6. Generates title, description, and tags from templates
7. Uploads to YouTube via **YouTube Data API v3** with OAuth2

---

## Requirements

- Python 3.12+
- FFmpeg (installed automatically on GitHub Actions; install locally with `sudo apt install ffmpeg` or `brew install ffmpeg`)
- Accounts / API keys:
  - [Suno](https://suno.com) account (free tier works)
  - [Replicate](https://replicate.com) account (~$0.05/image with Flux 1.1 Pro)
  - Google Cloud project with YouTube Data API v3 enabled

---

## Local Setup

### 1. Clone and install

```bash
git clone https://github.com/YOUR_USERNAME/lofi-pipeline.git
cd lofi-pipeline
pip install -r requirements.txt
```

### 2. Get API credentials

**Suno cookie:**
1. Log in to [suno.com](https://suno.com)
2. Open DevTools → Network tab → click any API request
3. Copy the full `Cookie:` header value
4. Set: `export SUNO_COOKIE="your_cookie_value"`

**Replicate API token:**
1. Go to [replicate.com/account/api-tokens](https://replicate.com/account/api-tokens)
2. Create a new token
3. Set: `export REPLICATE_API_TOKEN="r8_your_token"`

**YouTube OAuth2:**
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project → enable **YouTube Data API v3**
3. Create OAuth2 credentials (Desktop app type)
4. Add your Google account as a test user
5. Run the setup script:

```bash
python scripts/setup_youtube_oauth.py \
  --client-id YOUR_CLIENT_ID \
  --client-secret YOUR_CLIENT_SECRET
```

6. Copy the printed JSON for the next step.

### 3. Run locally

```bash
# Test config loading (no API needed)
python -m src.config

# Test metadata generation (no API needed)
python -m src.metadata_generator

# Test image generation (Replicate API needed)
REPLICATE_API_TOKEN=xxx python -m src.image_generator

# Test music generation (Suno cookie needed)
SUNO_COOKIE=xxx python -m src.music_generator

# Full pipeline
export SUNO_COOKIE="..."
export REPLICATE_API_TOKEN="..."
export YOUTUBE_CLIENT_ID="..."
export YOUTUBE_CLIENT_SECRET="..."
export YOUTUBE_OAUTH_TOKEN='{"token":"...","refresh_token":"...",...}'
python -m src.pipeline
```

---

## GitHub Actions Setup

### 1. Add secrets

Go to your repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Value |
|--------|-------|
| `SUNO_COOKIE` | Full Cookie header from Suno DevTools |
| `REPLICATE_API_TOKEN` | Your Replicate token |
| `YOUTUBE_CLIENT_ID` | Google OAuth2 Client ID |
| `YOUTUBE_CLIENT_SECRET` | Google OAuth2 Client Secret |
| `YOUTUBE_OAUTH_TOKEN` | JSON output from `setup_youtube_oauth.py` |

### 2. Schedule

The workflow runs daily at **UTC 10:00** (13:00 Turkey time). Modify the cron in [`.github/workflows/daily-video.yml`](.github/workflows/daily-video.yml):

```yaml
on:
  schedule:
    - cron: '0 10 * * *'
  workflow_dispatch:    # Also allows manual runs
```

### 3. Manual trigger

Go to **Actions → Daily Lo-Fi Video → Run workflow** to trigger immediately.

---

## Cost Estimate (~$15/month)

| Service | Cost | Notes |
|---------|------|-------|
| Replicate Flux 1.1 Pro | ~$0.05/image × 30 = **$1.50/mo** | 1920×1080, 28 steps |
| Suno AI | **$0** (unofficial API) | May require Pro plan for volume |
| GitHub Actions | **$0** (2000 min free/mo) | ~90 min/day = 2700 min → need paid plan |
| GitHub Actions paid | ~$0.008/min × 700 min = **$5.60/mo** | For minutes beyond free tier |
| Google Cloud | **$0** | YouTube API is free |
| **Total** | **~$7–15/mo** | Varies by Suno usage |

---

## Configuration

All settings are in [`config/config.yaml`](config/config.yaml):

| Key | Description |
|-----|-------------|
| `music.tracks_per_mix` | Number of Suno tracks to generate (18 = ~1 hour) |
| `music.crossfade_duration` | Crossfade seconds between tracks |
| `music.target_mix_duration` | Target audio length in seconds (3600 = 1 hour) |
| `image.model` | Replicate model ID |
| `video.ken_burns.enabled` | Enable slow zoom effect |
| `video.visualizer.enabled` | Enable audio waveform bar |
| `video.color_grade.*` | FFmpeg eq + vignette settings |
| `youtube.privacy_status` | "public", "unlisted", or "private" |

Prompts, moods, scenes, and title templates are in [`config/prompts.yaml`](config/prompts.yaml).

---

## Troubleshooting

### Suno cookie expired
Symptom: `PermissionError: Suno returned 401 Unauthorized`

Fix:
1. Log in to [suno.com](https://suno.com)
2. Open DevTools → Network → any request → copy Cookie header
3. Update the `SUNO_COOKIE` GitHub secret

### YouTube token expired
Symptom: `google.auth.exceptions.RefreshError`

The `refresh_token` is long-lived but the `access_token` expires in 1 hour. The pipeline automatically refreshes it. If refresh fails:
1. Re-run `python scripts/setup_youtube_oauth.py ...`
2. Update `YOUTUBE_OAUTH_TOKEN` secret

### FFmpeg encoding fails
The pipeline has two modes:
1. **Full** — Ken Burns + visualizer + color grade (preferred)
2. **Fallback** — Ken Burns only (simpler, more compatible)

If both fail, check the GitHub Actions log for the FFmpeg stderr output.

### Disk space full (GitHub Actions)
The `ubuntu-latest` runner has ~14 GB free. A 1-hour lo-fi video is typically 2–4 GB. The pipeline cleans up temp files automatically. If you still run out of disk:
- Increase video CRF (lower quality, smaller file): set `video.crf: 24` in config.yaml
- Reduce `music.tracks_per_mix` to generate fewer tracks

### Pipeline timeout
Default timeout is 120 minutes. FFmpeg encoding takes 30–60 min. If needed, increase `timeout-minutes` in the workflow file.

---

## Tests

```bash
python -m pytest tests/ -v
```

Tests cover:
- `test_audio_processor.py` — timestamp formatting, normalization, crossfade logic
- `test_metadata_generator.py` — title/description templating, tag validation
- `test_pipeline.py` — config loading, output directory creation

---

## Project Structure

```
lofi-pipeline/
├── .github/workflows/daily-video.yml   # GitHub Actions cron job
├── src/
│   ├── config.py                       # Config loader + output dirs
│   ├── music_generator.py              # Suno API integration
│   ├── audio_processor.py              # FFmpeg audio mixing
│   ├── image_generator.py              # Replicate Flux image generation
│   ├── video_assembler.py              # FFmpeg video assembly
│   ├── metadata_generator.py           # YouTube title/description/tags
│   ├── youtube_uploader.py             # YouTube Data API v3 upload
│   └── pipeline.py                     # Main orchestrator
├── config/
│   ├── config.yaml                     # All settings
│   └── prompts.yaml                    # Music moods, image prompts, templates
├── scripts/
│   └── setup_youtube_oauth.py          # First-time OAuth2 token setup
├── tests/
│   ├── test_audio_processor.py
│   ├── test_metadata_generator.py
│   └── test_pipeline.py
└── requirements.txt
```
