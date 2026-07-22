from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from .config import GOOGLE_SCOPES, settings
from .token_store import token_store


def _credentials_for(user_email: str) -> Credentials:
    stored = token_store.get(user_email)
    if stored is None:
        raise LookupError(f"No stored Google credentials for {user_email}")

    creds = Credentials(
        token=stored.access_token,
        refresh_token=stored.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=GOOGLE_SCOPES,
        expiry=stored.access_token_expiry,
    )

    if not creds.valid:
        creds.refresh(GoogleAuthRequest())
        stored.access_token = creds.token
        stored.access_token_expiry = creds.expiry
        token_store.set(user_email, stored)

    return creds


def calendar_client(user_email: str):
    return build("calendar", "v3", credentials=_credentials_for(user_email), cache_discovery=False)


def tasks_client(user_email: str):
    return build("tasks", "v1", credentials=_credentials_for(user_email), cache_discovery=False)
