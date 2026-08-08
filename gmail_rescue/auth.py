"""One-time OAuth per account, then never again.

Two accounts, two token files. This is the entire reason this tool exists: the
Claude chat connector can only attach one Gmail account at a time, while these
tokens sit side by side and let one command operate either account.

The flow opens a browser on THIS machine and Google returns the approval to a
localhost address on THIS machine. That is why the tool has to run on your own
computer rather than in a remote container -- Google retired the copy-paste
"out of band" flow in January 2023, so there is no headless alternative for a
Desktop-app client.
"""

from __future__ import annotations

import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from .api import SCOPES

CREDENTIALS_FILE = "credentials.json"
TOKEN_DIR = "tokens"

ACCOUNT_HINTS = {
    "personal": "james.bonaguro@gmail.com",
    "business": "james@intersectionstrategies.co",
}


def token_path(account: str) -> str:
    return os.path.join(TOKEN_DIR, f"{account}.json")


def _load_credentials(account: str) -> Credentials | None:
    path = token_path(account)
    if not os.path.exists(path):
        return None
    try:
        return Credentials.from_authorized_user_file(path, SCOPES)
    except ValueError:
        return None


def authorize(account: str, force: bool = False) -> Credentials:
    """Return valid credentials, running the browser flow only when needed."""
    os.makedirs(TOKEN_DIR, exist_ok=True)
    creds = None if force else _load_credentials(account)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token and not force:
        try:
            creds.refresh(Request())
            _save(account, creds)
            return creds
        except Exception as err:  # refresh tokens expire in testing mode
            print(f"  Could not refresh the saved token ({err}).")
            print("  Re-running the browser approval instead.")

    if not os.path.exists(CREDENTIALS_FILE):
        raise SystemExit(
            f"\n{CREDENTIALS_FILE} not found in {os.getcwd()}.\n"
            "This is the file you download from Google Cloud Console after "
            "creating a Desktop app OAuth client.\n"
            "Step-by-step instructions are in SETUP.md.\n"
        )

    hint = ACCOUNT_HINTS.get(account, "")
    print(f"\nA browser window is about to open.")
    print(f"  Sign in as: {hint}")
    print("  If you are already signed in as a different Google account, use")
    print("  'Use another account' on that screen -- picking the wrong one here")
    print("  is the single easiest mistake to make.")
    print("  You will see an 'unverified app' warning. That is expected for an")
    print("  app in testing mode that you created yourself. Click Advanced, then")
    print("  'Go to ... (unsafe)'.\n")

    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent",
                                  login_hint=hint or None)
    _save(account, creds)
    return creds


def _save(account: str, creds: Credentials) -> None:
    path = token_path(account)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(creds.to_json())
    os.chmod(path, 0o600)


def get_service(account: str, force_auth: bool = False):
    """Build an authenticated Gmail service for one account."""
    creds = authorize(account, force=force_auth)
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def verify_scopes(creds: Credentials) -> list[str]:
    """Return any required scopes the stored token is missing."""
    granted = set(creds.scopes or [])
    return [s for s in SCOPES if s not in granted]
