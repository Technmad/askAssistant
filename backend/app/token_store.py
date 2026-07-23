"""Refresh-token storage. SQLite for local dev (survives server restarts,
unlike the in-memory version this replaced) -- swap for a Postgres-backed
implementation behind this same get/set interface once a managed database
is wired up for production."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_DB_PATH = Path(__file__).parent.parent / "token_store.sqlite3"


@dataclass
class StoredToken:
    refresh_token: str
    access_token: str | None = None
    access_token_expiry: datetime | None = None  # naive UTC, matches google-auth's convention


class SqliteTokenStore:
    def __init__(self, db_path: Path = _DB_PATH) -> None:
        self._db_path = db_path
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tokens (
                    user_email TEXT PRIMARY KEY,
                    refresh_token TEXT NOT NULL,
                    access_token TEXT,
                    access_token_expiry TEXT
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def get(self, user_email: str) -> StoredToken | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT refresh_token, access_token, access_token_expiry FROM tokens WHERE user_email = ?",
                (user_email,),
            ).fetchone()
        if row is None:
            return None
        refresh_token, access_token, expiry_str = row
        expiry = datetime.fromisoformat(expiry_str) if expiry_str else None
        return StoredToken(refresh_token=refresh_token, access_token=access_token, access_token_expiry=expiry)

    def set(self, user_email: str, token: StoredToken) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tokens (user_email, refresh_token, access_token, access_token_expiry)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_email) DO UPDATE SET
                    refresh_token = excluded.refresh_token,
                    access_token = excluded.access_token,
                    access_token_expiry = excluded.access_token_expiry
                """,
                (
                    user_email,
                    token.refresh_token,
                    token.access_token,
                    token.access_token_expiry.isoformat() if token.access_token_expiry else None,
                ),
            )


token_store = SqliteTokenStore()
