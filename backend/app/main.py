from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from googleapiclient.errors import HttpError

from .auth import get_current_user
from .auth import router as auth_router
from .config import settings
from .google_clients import calendar_client

app = FastAPI(title="AI Personal Assistant")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/calendar/events")
def list_upcoming_events(user_email: str = Depends(get_current_user)):
    """Auth-spike proof: login -> JWT -> one real Google Calendar API call."""
    try:
        service = calendar_client(user_email)
        now = datetime.now(timezone.utc).isoformat()
        result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=now,
                maxResults=10,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
    except HttpError as exc:
        raise HTTPException(status_code=502, detail=f"Google Calendar API error: {exc}") from exc

    events = [
        {
            "id": item["id"],
            "summary": item.get("summary", "(no title)"),
            "start": item["start"].get("dateTime", item["start"].get("date")),
        }
        for item in result.get("items", [])
    ]
    return {"events": events}
