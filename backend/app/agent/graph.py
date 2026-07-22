"""LangGraph agent: interpret -> resolve -> respond.

Stateless per call -- no checkpointer, no interrupt() (see PLAN.md's
stateless-confirmation decision). Every /chat call re-derives everything
fresh from the request payload; only the LLM step (interpret_node) is
non-deterministic, everything downstream is plain, testable Python.
"""

import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from langgraph.graph import END, StateGraph

from ..nlu.datetime_resolver import resolve_instant, resolve_range
from ..services import calendar as calendar_service
from ..services import tasks as tasks_service
from ..services.resolve import resolve_target
from .interpret import interpret
from .schema import ChatResponse, HistoryTurn, ProposedAction, ReferencedEntity
from .state import AgentState

DEFAULT_EVENT_DURATION_MINUTES = 30

_ENTITY_TYPE_FOR_INTENT = {
    "calendar_update": "event",
    "calendar_delete": "event",
    "task_update": "task",
    "task_complete": "task",
    "task_delete": "task",
}

_MUTATE_ACTION = {
    "calendar_update": "calendar.update",
    "calendar_delete": "calendar.delete",
    "task_update": "task.update",
    "task_complete": "task.complete",
    "task_delete": "task.delete",
}


def _new_request_id() -> str:
    return uuid.uuid4().hex


def _now_dt(state: AgentState) -> datetime:
    return datetime.fromisoformat(state["now"])


def interpret_node(state: AgentState) -> dict:
    history = [HistoryTurn(**t) for t in state.get("recent_history", [])]
    last_entity = (
        ReferencedEntity(**state["last_referenced_entity"])
        if state.get("last_referenced_entity")
        else None
    )
    result = interpret(
        message=state["message"],
        recent_history=history,
        last_referenced_entity=last_entity,
        now=state["now"],
        timezone=state["timezone"],
    )
    return {"interpretation": result}


def route_after_interpret(state: AgentState) -> str:
    intent = state["interpretation"].intent
    if intent in ("calendar_create", "task_create"):
        return "create"
    if intent in _ENTITY_TYPE_FOR_INTENT:
        return "mutate_existing"
    if intent in ("calendar_read", "task_read"):
        return "read"
    return "chitchat"


def create_node(state: AgentState) -> dict:
    interp = state["interpretation"]
    now = _now_dt(state)
    is_calendar = interp.intent == "calendar_create"

    title = interp.title
    if not title and is_calendar and interp.attendee_names:
        # Small/fast models don't reliably synthesize a title from context
        # even when told to -- this specific pattern (meeting + named
        # attendees, no explicit title) is common enough to just handle
        # deterministically rather than depend on model instruction-following.
        title = f"Meeting with {' and '.join(interp.attendee_names)}"

    if not title:
        return {"response": ChatResponse(type="clarify", message="What should I call this?").model_dump()}
    interp.title = title

    if interp.attendee_names and not interp.attendee_emails:
        return {
            "response": ChatResponse(
                type="clarify", message=f"What's {interp.attendee_names[0]}'s email address?"
            ).model_dump()
        }

    resolved = resolve_instant(interp.time_phrase, now) if interp.time_phrase else None

    if is_calendar and resolved is None:
        return {
            "response": ChatResponse(
                type="clarify", message=f'What time should "{interp.title}" be?'
            ).model_dump()
        }

    request_id = _new_request_id()

    if is_calendar:
        duration = interp.duration_minutes or DEFAULT_EVENT_DURATION_MINUTES
        end = resolved + timedelta(minutes=duration)
        params = {
            "summary": interp.title,
            "start": resolved.isoformat(),
            "end": end.isoformat(),
            "time_zone": state["timezone"],
            "attendees": interp.attendee_emails or None,
        }
        summary_line = f'Create "{interp.title}" on {resolved.strftime("%A %b %d at %I:%M %p")}'
        action = "calendar.create"
    else:
        params = {"title": interp.title, "due": resolved.isoformat() if resolved else None}
        due_note = f' due {resolved.strftime("%A %b %d")}' if resolved else ""
        summary_line = f'Create task "{interp.title}"{due_note}'
        action = "task.create"

    proposed = ProposedAction(request_id=request_id, action=action, entity_id=None, params=params)
    return {
        "response": ChatResponse(
            type="propose", message=f"{summary_line} -- confirm?", proposed_action=proposed
        ).model_dump()
    }


def mutate_existing_node(state: AgentState) -> dict:
    interp = state["interpretation"]
    now = _now_dt(state)
    entity_type = _ENTITY_TYPE_FOR_INTENT[interp.intent]
    label_key = "summary" if entity_type == "event" else "title"

    if not interp.target_phrase:
        noun = "event" if entity_type == "event" else "task"
        return {"response": ChatResponse(type="clarify", message=f"Which {noun} do you mean?").model_dump()}

    result = resolve_target(entity_type, interp.target_phrase, state["user_email"])

    if result.status == "not_found":
        return {
            "response": ChatResponse(
                type="error", message=f'I couldn\'t find "{interp.target_phrase}".'
            ).model_dump()
        }

    if result.status == "ambiguous":
        options = "; ".join(c[label_key] for c in result.candidates)
        return {
            "response": ChatResponse(
                type="clarify", message=f"Which one did you mean -- {options}?"
            ).model_dump()
        }

    target = result.candidates[0]
    action = _MUTATE_ACTION[interp.intent]
    request_id = _new_request_id()
    params: dict = {}

    if interp.intent == "calendar_delete":
        summary_line = f'Delete "{target["summary"]}"'
    elif interp.intent == "task_delete":
        summary_line = f'Delete task "{target["title"]}"'
    elif interp.intent == "task_complete":
        summary_line = f'Mark "{target["title"]}" as completed'
    elif interp.intent == "calendar_update":
        new_time = resolve_instant(interp.time_phrase, now) if interp.time_phrase else None
        if interp.time_phrase and new_time is None:
            return {
                "response": ChatResponse(
                    type="clarify", message=f'What time should I move "{target["summary"]}" to?'
                ).model_dump()
            }
        if new_time:
            duration = interp.duration_minutes or DEFAULT_EVENT_DURATION_MINUTES
            params["start"] = new_time.isoformat()
            params["end"] = (new_time + timedelta(minutes=duration)).isoformat()
            params["time_zone"] = state["timezone"]
        if interp.title:
            params["summary"] = interp.title
        if not params:
            return {
                "response": ChatResponse(
                    type="clarify", message=f'What should change about "{target["summary"]}"?'
                ).model_dump()
            }
        change = f'to {new_time.strftime("%A %b %d at %I:%M %p")}' if new_time else f'to "{interp.title}"'
        summary_line = f'Move "{target["summary"]}" {change}'
    else:  # task_update
        new_due = resolve_instant(interp.time_phrase, now) if interp.time_phrase else None
        if new_due:
            params["due"] = new_due.isoformat()
        if interp.title:
            params["title"] = interp.title
        if not params:
            return {
                "response": ChatResponse(
                    type="clarify", message=f'What should change about "{target["title"]}"?'
                ).model_dump()
            }
        summary_line = f'Update task "{target["title"]}"'

    proposed = ProposedAction(request_id=request_id, action=action, entity_id=target["id"], params=params)
    ref = ReferencedEntity(type=entity_type, id=target["id"], summary=target[label_key])
    return {
        "response": ChatResponse(
            type="propose",
            message=f"{summary_line} -- confirm?",
            proposed_action=proposed,
            referenced_entity=ref,
        ).model_dump()
    }


def read_node(state: AgentState) -> dict:
    interp = state["interpretation"]
    now = _now_dt(state)
    is_calendar = interp.intent == "calendar_read"

    date_range = resolve_range(interp.range_phrase, now) if interp.range_phrase else None
    start, end = (date_range.start, date_range.end) if date_range else (now, now + timedelta(days=7))

    # Calendar's events().list requires timeMin/timeMax as RFC3339 WITH a UTC
    # offset (unlike create/update, there's no separate timeZone field here) --
    # attach the user's own offset rather than assume UTC.
    tz = ZoneInfo(state["timezone"])
    time_min = start.replace(tzinfo=tz).isoformat()
    time_max = end.replace(tzinfo=tz).isoformat()

    if is_calendar:
        items = calendar_service.list_events(state["user_email"], time_min=time_min, time_max=time_max)
        if not items:
            message = "Nothing on your calendar in that range."
        else:
            lines = [f'- {item["summary"]} ({item["start"]})' for item in items]
            message = "Here's what's on your calendar:\n" + "\n".join(lines)
    else:
        # Only filter by due date when the user actually named a range --
        # a bare "show my tasks" should show everything open, not just a
        # 7-day default window (tasks are reviewed as a full list more often
        # than a calendar is).
        due_kwargs = {"due_min": time_min, "due_max": time_max} if date_range else {}
        items = [
            t for t in tasks_service.list_tasks(state["user_email"], **due_kwargs) if t["status"] != "completed"
        ]
        if not items:
            message = "No open tasks in that range." if date_range else "No open tasks."
        else:
            lines = [f'- {t["title"]}' + (f' (due {t["due"]})' if t["due"] else "") for t in items]
            message = "Here are your open tasks:\n" + "\n".join(lines)

    return {"response": ChatResponse(type="result", message=message).model_dump()}


def chitchat_node(state: AgentState) -> dict:
    interp = state["interpretation"]
    if interp.intent == "chitchat":
        message = "I can help with your Calendar and Tasks -- try asking me to schedule something or show your week."
    else:
        message = "I didn't quite catch what you'd like me to do with your calendar or tasks -- could you rephrase?"
    return {"response": ChatResponse(type="clarify", message=message).model_dump()}


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("interpret", interpret_node)
    graph.add_node("create", create_node)
    graph.add_node("mutate_existing", mutate_existing_node)
    graph.add_node("read", read_node)
    graph.add_node("chitchat", chitchat_node)

    graph.set_entry_point("interpret")
    graph.add_conditional_edges(
        "interpret",
        route_after_interpret,
        {"create": "create", "mutate_existing": "mutate_existing", "read": "read", "chitchat": "chitchat"},
    )
    for node in ("create", "mutate_existing", "read", "chitchat"):
        graph.add_edge(node, END)

    return graph.compile()


agent_graph = build_graph()
