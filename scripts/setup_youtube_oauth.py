"""
First-time YouTube OAuth2 token setup.

Run this script locally (not in CI) to generate OAuth2 credentials for the
YouTube Data API. A browser window will open for Google account authorization.
The resulting token JSON is printed to stdout — copy it and add it as the
GitHub secret YOUTUBE_OAUTH_TOKEN.

Usage:
    python scripts/setup_youtube_oauth.py \\
        --client-id YOUR_GOOGLE_CLIENT_ID \\
        --client-secret YOUR_GOOGLE_CLIENT_SECRET

Prerequisites:
    1. Create a Google Cloud project at https://console.cloud.google.com/
    2. Enable the YouTube Data API v3
    3. Create OAuth2 credentials (Desktop app type)
    4. Add your Google account as a test user (OAuth consent screen)

After running:
    - Copy the printed JSON
    - Go to your GitHub repo → Settings → Secrets and variables → Actions
    - Create secret: YOUTUBE_OAUTH_TOKEN = <paste JSON>
"""

import argparse
import json
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def main() -> None:
    """Run the OAuth2 flow and print the token JSON."""
    parser = argparse.ArgumentParser(
        description="Obtain YouTube OAuth2 tokens for the lo-fi pipeline"
    )
    parser.add_argument("--client-id", required=True, help="Google OAuth2 Client ID")
    parser.add_argument("--client-secret", required=True, help="Google OAuth2 Client Secret")
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Local port for OAuth2 redirect (default: 8080)",
    )
    args = parser.parse_args()

    client_config = {
        "installed": {
            "client_id": args.client_id,
            "client_secret": args.client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [f"http://localhost:{args.port}", "urn:ietf:wg:oauth:2.0:oob"],
        }
    }

    print("Starting OAuth2 flow — your browser will open.", file=sys.stderr)
    print("Log in with the Google account that owns the 'Chill Drift' YouTube channel.", file=sys.stderr)
    print("", file=sys.stderr)

    flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)
    creds = flow.run_local_server(port=args.port, prompt="consent", access_type="offline")

    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes) if creds.scopes else SCOPES,
        "expiry": creds.expiry.isoformat() if creds.expiry else None,
    }

    print("", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print("SUCCESS — copy the JSON below into GitHub Secret YOUTUBE_OAUTH_TOKEN:", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print("", file=sys.stderr)

    # Print JSON to stdout so it can be piped/captured
    print(json.dumps(token_data, indent=2))

    print("", file=sys.stderr)
    print("Done! Add this as GitHub Secret: YOUTUBE_OAUTH_TOKEN", file=sys.stderr)
    print("Also add YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET secrets.", file=sys.stderr)


if __name__ == "__main__":
    main()
