"""The hardened /execute handler (PLAN.md §2): dedupe -> act -> cache.

No separate pre-flight "does this still exist" check -- the mutating
Google API call itself is the validation, and a 404/410 on that call IS
the staleness signal (confirmed empirically: Calendar raises 410 on an
already-deleted event; Tasks' delete is idempotent and never does).
"""

import time

from googleapiclient.errors import HttpError

from ..services import calendar as calendar_service
from ..services import tasks as tasks_service
from .schema import ExecuteResponse, ProposedAction, ReferencedEntity

_DEDUPE_TTL_SECONDS = 600
# Keyed by (user_email, request_id) -- request_id is generated fresh per
# proposed action shown to the user, NOT derived from the action's content,
# so two genuinely-intended repeats of the same action are never conflated.
_dedupe_cache: dict[tuple[str, str], tuple[float, dict]] = {}


def _cache_get(user_email: str, request_id: str) -> dict | None:
    key = (user_email, request_id)
    entry = _dedupe_cache.get(key)
    if entry is None:
        return None
    stored_at, result = entry
    if time.time() - stored_at > _DEDUPE_TTL_SECONDS:
        del _dedupe_cache[key]
        return None
    return result


def _cache_set(user_email: str, request_id: str, result: dict) -> None:
    _dedupe_cache[(user_email, request_id)] = (time.time(), result)


def _is_gone(exc: HttpError) -> bool:
    return exc.resp.status in (404, 410)


def execute_action(user_email: str, action: ProposedAction) -> ExecuteResponse:
    cached = _cache_get(user_email, action.request_id)
    if cached is not None:
        return ExecuteResponse(**cached)

    try:
        response = _dispatch(user_email, action)
    except HttpError as exc:
        if action.entity_id and _is_gone(exc):
            response = ExecuteResponse(
                type="error",
                message="That item no longer exists -- it may have already been changed elsewhere.",
            )
        else:
            response = ExecuteResponse(type="error", message=f"Google API error: {exc}")

    _cache_set(user_email, action.request_id, response.model_dump())
    return response


def _dispatch(user_email: str, action: ProposedAction) -> ExecuteResponse:
    if action.action == "calendar.create":
        event = calendar_service.create_event(user_email, **action.params)
        return ExecuteResponse(
            type="result",
            message=f'Created "{event["summary"]}" on {event["start"]}.',
            referenced_entity=ReferencedEntity(type="event", id=event["id"], summary=event["summary"]),
        )
    if action.action == "calendar.update":
        event = calendar_service.update_event(user_email, action.entity_id, **action.params)
        return ExecuteResponse(
            type="result",
            message=f'Updated "{event["summary"]}".',
            referenced_entity=ReferencedEntity(type="event", id=event["id"], summary=event["summary"]),
        )
    if action.action == "calendar.delete":
        calendar_service.delete_event(user_email, action.entity_id)
        return ExecuteResponse(type="result", message="Deleted.")
    if action.action == "task.create":
        task = tasks_service.create_task(user_email, **action.params)
        return ExecuteResponse(
            type="result",
            message=f'Created task "{task["title"]}".',
            referenced_entity=ReferencedEntity(type="task", id=task["id"], summary=task["title"]),
        )
    if action.action == "task.update":
        task = tasks_service.update_task(user_email, action.entity_id, **action.params)
        return ExecuteResponse(
            type="result",
            message=f'Updated task "{task["title"]}".',
            referenced_entity=ReferencedEntity(type="task", id=task["id"], summary=task["title"]),
        )
    if action.action == "task.complete":
        task = tasks_service.complete_task(user_email, action.entity_id)
        return ExecuteResponse(
            type="result",
            message=f'Marked "{task["title"]}" as completed.',
            referenced_entity=ReferencedEntity(type="task", id=task["id"], summary=task["title"]),
        )
    if action.action == "task.reopen":
        task = tasks_service.reopen_task(user_email, action.entity_id)
        return ExecuteResponse(
            type="result",
            message=f'Reopened "{task["title"]}".',
            referenced_entity=ReferencedEntity(type="task", id=task["id"], summary=task["title"]),
        )
    if action.action == "task.delete":
        tasks_service.delete_task(user_email, action.entity_id)
        return ExecuteResponse(type="result", message="Deleted.")

    raise ValueError(f"Unknown action: {action.action}")
