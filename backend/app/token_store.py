"""Refresh-token storage. In-memory for the auth spike — swap for a
Postgres-backed implementation (see PLAN.md §1/§8) behind this same
get/set interface once Supabase is wired up."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class StoredToken:
    refresh_token: str
    access_token: str | None = None
    access_token_expiry: datetime | None = None  # naive UTC, matches google-auth's convention


class InMemoryTokenStore:
    def __init__(self) -> None:
        self._tokens: dict[str, StoredToken] = {}

    def get(self, user_email: str) -> StoredToken | None:
        return self._tokens.get(user_email)

    def set(self, user_email: str, token: StoredToken) -> None:
        self._tokens[user_email] = token


token_store = InMemoryTokenStore()
