"""Manual verification endpoints for the Calendar/Tasks service wrappers,
ahead of the LangGraph agent (session 3) calling these functions directly.
Not part of the wire contract in PLAN.md §2 — delete this router once the
agent exists and there's no more need to curl these individually."""

from fastapi import APIRouter, Depends, HTTPException
from googleapiclient.errors import HttpError
from pydantic import BaseModel

from .auth import get_current_user
from .services import calendar as calendar_service
from .services import tasks as tasks_service
from .services.resolve import EntityType, resolve_target

router = APIRouter(prefix="/debug", tags=["debug"])


def _wrap(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except HttpError as exc:
        raise HTTPException(status_code=502, detail=f"Google API error: {exc}") from exc


class CreateEventBody(BaseModel):
    summary: str
    start: str
    end: str
    time_zone: str
    attendees: list[str] | None = None


class UpdateEventBody(BaseModel):
    summary: str | None = None
    start: str | None = None
    end: str | None = None
    time_zone: str | None = None


class CreateTaskBody(BaseModel):
    title: str
    due: str | None = None


class UpdateTaskBody(BaseModel):
    title: str | None = None
    due: str | None = None
    status: str | None = None


@router.get("/events")
def list_events(user_email: str = Depends(get_current_user)):
    return _wrap(calendar_service.list_events, user_email)


@router.post("/events")
def create_event(body: CreateEventBody, user_email: str = Depends(get_current_user)):
    return _wrap(calendar_service.create_event, user_email, **body.model_dump())


@router.patch("/events/{event_id}")
def update_event(event_id: str, body: UpdateEventBody, user_email: str = Depends(get_current_user)):
    return _wrap(calendar_service.update_event, user_email, event_id, **body.model_dump())


@router.delete("/events/{event_id}")
def delete_event(event_id: str, user_email: str = Depends(get_current_user)):
    _wrap(calendar_service.delete_event, user_email, event_id)
    return {"deleted": event_id}


@router.get("/tasks")
def list_tasks(user_email: str = Depends(get_current_user)):
    return _wrap(tasks_service.list_tasks, user_email)


@router.post("/tasks")
def create_task(body: CreateTaskBody, user_email: str = Depends(get_current_user)):
    return _wrap(tasks_service.create_task, user_email, **body.model_dump())


@router.patch("/tasks/{task_id}")
def update_task(task_id: str, body: UpdateTaskBody, user_email: str = Depends(get_current_user)):
    return _wrap(tasks_service.update_task, user_email, task_id, **body.model_dump())


@router.post("/tasks/{task_id}/complete")
def complete_task(task_id: str, user_email: str = Depends(get_current_user)):
    return _wrap(tasks_service.complete_task, user_email, task_id)


@router.delete("/tasks/{task_id}")
def delete_task(task_id: str, user_email: str = Depends(get_current_user)):
    _wrap(tasks_service.delete_task, user_email, task_id)
    return {"deleted": task_id}


@router.get("/resolve")
def resolve(entity_type: EntityType, query: str, user_email: str = Depends(get_current_user)):
    result = resolve_target(entity_type, query, user_email)
    return {"status": result.status, "candidates": result.candidates}
