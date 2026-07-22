from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from googleapiclient.errors import HttpError

from .auth import get_current_user
from .auth import router as auth_router
from .config import settings
from .debug_routes import router as debug_router
from .services import calendar as calendar_service

app = FastAPI(title="AI Personal Assistant")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(debug_router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/calendar/events")
def list_upcoming_events(user_email: str = Depends(get_current_user)):
    """Auth-spike proof: login -> JWT -> one real Google Calendar API call."""
    try:
        events = calendar_service.list_events(user_email, max_results=10)
    except HttpError as exc:
        raise HTTPException(status_code=502, detail=f"Google Calendar API error: {exc}") from exc
    return {"events": events}
