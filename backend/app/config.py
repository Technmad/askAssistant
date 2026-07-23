from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str
    jwt_secret: str
    frontend_url: str = "http://localhost:3000"

    jwt_algorithm: str = "HS256"
    jwt_ttl_minutes: int = 45

    groq_api_key: str
    groq_model: str = "llama-3.3-70b-versatile"


settings = Settings()

GOOGLE_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/tasks",
    # Read-only contact lookup so a named attendee ("John") can resolve to
    # an email automatically when they're an existing Google Contact,
    # falling back to asking only when they genuinely aren't (PLAN.md §5).
    # Two separate scopes: Google splits explicitly-saved contacts from
    # "Other contacts" (auto-suggested from Gmail history but never saved).
    "https://www.googleapis.com/auth/contacts.readonly",
    "https://www.googleapis.com/auth/contacts.other.readonly",
]
