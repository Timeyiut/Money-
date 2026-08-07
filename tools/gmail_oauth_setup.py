#!/usr/bin/env python3
"""One-time local helper: authorize this app against your own Gmail account
and print the refresh token needed for the CI pipeline.

Run this on your own machine (never in CI):

    pip install -r tools/requirements.txt
    python3 tools/gmail_oauth_setup.py \
        --client-id "..." --client-secret "..."

It opens a browser for you to log into Gmail and grant read-only access.
Afterwards it prints the refresh token — copy it straight into the
GMAIL_REFRESH_TOKEN GitHub Actions secret. Nothing is written to disk here
and nothing in this repo ever sees your credentials.
"""
import argparse

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--client-secret", required=True)
    args = parser.parse_args()

    client_config = {
        "installed": {
            "client_id": args.client_id,
            "client_secret": args.client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }
    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    creds = flow.run_local_server(port=0)

    print("\nRefresh token (put this in the GMAIL_REFRESH_TOKEN secret):\n")
    print(creds.refresh_token)


if __name__ == "__main__":
    main()
