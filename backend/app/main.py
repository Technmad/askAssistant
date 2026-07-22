from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from googleapiclient.errors import HttpError

from .agent.execute import execute_action
from .agent.graph import agent_graph
from .agent.schema import ChatRequest, ChatResponse, ExecuteRequest, ExecuteResponse
from .auth import get_current_user
from .auth import router as auth_router
from .config import settings
from .services import calendar as calendar_service
from .services import tasks as tasks_service

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
    """Upcoming events for the side panel -- read-only, no agent involved."""
    try:
        events = calendar_service.list_events(user_email, max_results=10)
    except HttpError as exc:
        raise HTTPException(status_code=502, detail=f"Google Calendar API error: {exc}") from exc
    return {"events": events}


@app.get("/tasks/open")
def list_open_tasks(user_email: str = Depends(get_current_user)):
    """Open tasks for the side panel -- read-only, no agent involved."""
    try:
        tasks = [t for t in tasks_service.list_tasks(user_email) if t["status"] != "completed"]
    except HttpError as exc:
        raise HTTPException(status_code=502, detail=f"Google Tasks API error: {exc}") from exc
    return {"tasks": tasks}


@app.post("/chat", response_model=ChatResponse)
def chat(body: ChatRequest, user_email: str = Depends(get_current_user)):
    state = {
        "message": body.message,
        "recent_history": [turn.model_dump() for turn in body.recent_history],
        "last_referenced_entity": (
            body.last_referenced_entity.model_dump() if body.last_referenced_entity else None
        ),
        "now": body.now,
        "timezone": body.timezone,
        "user_email": user_email,
    }
    result = agent_graph.invoke(state)
    return result["response"]


@app.post("/execute", response_model=ExecuteResponse)
def execute(body: ExecuteRequest, user_email: str = Depends(get_current_user)):
    return execute_action(user_email, body.proposed_action)
