import time

import jwt as pyjwt
import requests
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow

from .config import GOOGLE_SCOPES, settings
from .token_store import StoredToken, token_store

router = APIRouter(prefix="/auth", tags=["auth"])

# PKCE code_verifier lives only on the Flow instance that generated it, but
# /login and /callback are separate HTTP requests (separate Flow instances).
# Bridge them with the one thing Google echoes back on the callback: `state`.
_pending_verifiers: dict[str, str] = {}


def _build_flow(state: str | None = None) -> Flow:
    client_config = {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.google_redirect_uri],
        }
    }
    return Flow.from_client_config(
        client_config,
        scopes=GOOGLE_SCOPES,
        state=state,
        redirect_uri=settings.google_redirect_uri,
    )


@router.get("/login")
def login():
    flow = _build_flow()
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        # Force the consent screen so Google reliably returns a refresh_token
        # even for a user who has logged in before (Google only issues one
        # on first consent otherwise).
        prompt="consent",
    )
    _pending_verifiers[state] = flow.code_verifier
    return RedirectResponse(auth_url)


@router.get("/callback")
def callback(code: str, state: str | None = None):
    flow = _build_flow(state=state)
    flow.code_verifier = _pending_verifiers.pop(state, None)
    flow.fetch_token(code=code)
    credentials = flow.credentials

    resp = requests.get(
        "https://www.googleapis.com/oauth2/v3/userinfo",
        headers={"Authorization": f"Bearer {credentials.token}"},
        timeout=10,
    )
    resp.raise_for_status()
    email = resp.json()["email"]

    if not credentials.refresh_token:
        raise HTTPException(
            status_code=400,
            detail=(
                "Google did not return a refresh token. Revoke prior access at "
                "https://myaccount.google.com/permissions and log in again."
            ),
        )

    token_store.set(
        email,
        StoredToken(
            refresh_token=credentials.refresh_token,
            access_token=credentials.token,
            access_token_expiry=credentials.expiry,
        ),
    )

    jwt_token = pyjwt.encode(
        {"sub": email, "exp": time.time() + settings.jwt_ttl_minutes * 60},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )

    return RedirectResponse(f"{settings.frontend_url}/auth/done?token={jwt_token}")


def get_current_user(authorization: str = Header(...)) -> str:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.removeprefix("Bearer ")
    try:
        payload = pyjwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except pyjwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired session token")
    return payload["sub"]
