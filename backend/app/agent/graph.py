"""LangGraph agent: interpret -> resolve -> respond.

Stateless per call -- no checkpointer, no interrupt() (see PLAN.md's
stateless-confirmation decision). Every /chat call re-derives everything
fresh from the request payload; only the LLM step (interpret_node) is
non-deterministic, everything downstream is plain, testable Python.
"""

import re
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from langgraph.graph import END, StateGraph

from ..nlu.datetime_resolver import extract_time_of_day, parse_relative_date, resolve_instant, resolve_range
from ..nlu.fuzzy_match import score as fuzzy_score
from ..services import calendar as calendar_service
from ..services import tasks as tasks_service
from ..services.contacts import find_email_by_name
from ..services.resolve import resolve_target
from .interpret import interpret
from .schema import (
    ChatResponse,
    Disambiguation,
    DisambiguationOption,
    HistoryTurn,
    ProposedAction,
    ReferencedEntity,
)
from .state import AgentState

DEFAULT_EVENT_DURATION_MINUTES = 30

_ENTITY_TYPE_FOR_INTENT = {
    "calendar_update": "event",
    "calendar_delete": "event",
    "task_update": "task",
    "task_complete": "task",
    "task_reopen": "task",
    "task_delete": "task",
}

_MUTATE_ACTION = {
    "calendar_update": "calendar.update",
    "calendar_delete": "calendar.delete",
    "task_update": "task.update",
    "task_complete": "task.complete",
    "task_reopen": "task.reopen",
    "task_delete": "task.delete",
}


def _new_request_id() -> str:
    return uuid.uuid4().hex


def _now_dt(state: AgentState) -> datetime:
    return datetime.fromisoformat(state["now"])


def _missing_datetime_part(time_phrase: str | None, now: datetime) -> str | None:
    """Returns 'date', 'time', 'both', or None (fully specified) for a
    calendar event. A phrase can independently lack either half ("2pm" has
    a time but no day; "tomorrow" has a day but no time) -- asking "what
    time?" when the day is what's actually missing just re-triggers the
    same unanswerable question forever."""
    if not time_phrase:
        return "both"
    has_date = parse_relative_date(time_phrase, now) is not None
    has_time = extract_time_of_day(time_phrase) is not None
    if has_date and has_time:
        return None
    if has_date:
        return "time"
    if has_time:
        return "date"
    return "both"


def _missing_part_word(missing: str) -> str:
    return {"date": "day", "time": "time"}.get(missing, "day and time")


def _task_due_iso(dt: datetime) -> str:
    # Google Tasks' `due` field requires a full RFC3339 timestamp with a UTC
    # marker (it discards the time-of-day regardless), so only the date part
    # is meaningful -- always serialize as UTC midnight rather than pass the
    # naive local wall-clock time through, which Google's API rejects outright.
    return f"{dt.date().isoformat()}T00:00:00.000Z"


_ATTENDEE_FALLBACK_PATTERN = re.compile(r"\bwith\s+([A-Z][a-zA-Z]+)\b")


def _fallback_attendee_name(*texts: str) -> str | None:
    """The LLM inconsistently recognizes "with {Name}" as an attendee to
    invite -- observed silently dropping a real name (title became "Meeting
    with Rishabh" but attendee_names stayed empty, so nobody got invited).
    A false-positive match here just costs one extra "what's X's email?"
    clarify question; a missed real name costs a meeting nobody finds out
    about -- the asymmetry favors this deterministic catch-all."""
    for text in texts:
        match = _ATTENDEE_FALLBACK_PATTERN.search(text)
        if match:
            return match.group(1)
    return None


_BULK_PATTERN = re.compile(
    r"\ball(?:\s+(?:of\s+them|four|4|three|3|two|2))?\b|\bboth\b|\bevery(?:\s+one)?\b|\beach\s+one\b",
    re.IGNORECASE,
)


def _mentions_bulk(message: str) -> bool:
    """We only ever resolve_target to a single item -- if the user's message
    signals "all of them"/"both"/"every", don't let the LLM guess at some
    single target (observed failure: it latched onto an unrelated real task
    instead of recognizing the request was for multiple items)."""
    return bool(_BULK_PATTERN.search(message))


def _format_candidate(candidate: dict, entity_type: str, timezone_name: str) -> str:
    """Disambiguation options must show what actually distinguishes them --
    identically-named candidates (e.g. two events both called "Meeting with
    Asmita") are unanswerable if only the name is shown."""
    label_key = "summary" if entity_type == "event" else "title"
    name = candidate[label_key]
    raw = candidate["start"] if entity_type == "event" else candidate.get("due")

    if not raw:
        return f'"{name}" (no due date)' if entity_type == "task" else f'"{name}"'
    try:
        dt = datetime.fromisoformat(raw).astimezone(ZoneInfo(timezone_name))
    except ValueError:
        return f'"{name}"'

    if entity_type == "event":
        return f'"{name}" ({dt.strftime("%a %b %d, %I:%M %p")})'
    return f'"{name}" (due {dt.strftime("%a %b %d")})'


_ORDINAL_WORDS = {
    # Deliberately NOT including word-numbers ("one", "two"...) -- "the 2pm
    # ONE" uses "one" as a generic noun, not the ordinal "first", and matching
    # it as index 0 previously returned the wrong candidate entirely.
    "first": 0, "1st": 0,
    "second": 1, "2nd": 1,
    "third": 2, "3rd": 2,
    "fourth": 3, "4th": 3,
    "fifth": 4, "5th": 4,
}  # fmt: skip

_MATCH_THRESHOLD = 0.5


def _match_pending_candidate(message: str, options: list[dict], timezone_name: str) -> dict | None:
    """Resolves a reply to a disambiguation question ("the second one", "the
    2pm one", or the option's own text copied back) against what was ACTUALLY
    offered last turn, rather than re-deriving a target from scratch -- which
    is what silently went wrong before this existed (the user answering with
    a time, not a name, had nothing to fuzzy-match against event titles)."""
    lowered = message.lower().strip()
    stripped = lowered.strip(".! ")

    if stripped == "last" and options:
        return options[-1]

    # An explicit time-of-day ("the 2pm one") is compared against each
    # candidate's ACTUAL time -- fuzzy-matching "2pm" as text against a label
    # showing "02:00 PM" barely overlaps character-for-character, so this
    # must parse and compare real times rather than match strings.
    mentioned_time = extract_time_of_day(lowered)
    if mentioned_time:
        tz = ZoneInfo(timezone_name)
        matches = []
        for opt in options:
            if not opt.get("when"):
                continue
            try:
                dt = datetime.fromisoformat(opt["when"]).astimezone(tz)
            except ValueError:
                continue
            if (dt.hour, dt.minute) == (mentioned_time.hour, mentioned_time.minute):
                matches.append(opt)
        if len(matches) == 1:
            return matches[0]

    for word, idx in _ORDINAL_WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", lowered) and idx < len(options):
            return options[idx]
    if stripped.isdigit() and 0 <= int(stripped) - 1 < len(options):
        return options[int(stripped) - 1]

    # Fall back to matching the option's own displayed label text, e.g. the
    # user copies "Fri Jul 24, 02:00 PM" back verbatim.
    scored = [(fuzzy_score(lowered, opt["label"].lower()), opt) for opt in options]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    if scored and scored[0][0] >= _MATCH_THRESHOLD:
        if len(scored) == 1 or scored[0][0] - scored[1][0] > 0.05:
            return scored[0][1]

    return None


def _find_conflicts(
    user_email: str, start: datetime, end: datetime, timezone_name: str, exclude_event_id: str | None = None
) -> list[dict]:
    # Google doesn't prevent double-booking on its own -- querying with the
    # new slot as timeMin/timeMax returns exactly the events that overlap it
    # (Calendar's own semantics), so no overlap math is needed here.
    tz = ZoneInfo(timezone_name)
    events = calendar_service.list_events(
        user_email, time_min=start.replace(tzinfo=tz).isoformat(), time_max=end.replace(tzinfo=tz).isoformat()
    )
    return [e for e in events if e["id"] != exclude_event_id]


def _conflict_note(conflicts: list[dict]) -> str:
    if not conflicts:
        return ""
    names = ", ".join(f'"{c["summary"]}"' for c in conflicts)
    return f" Note: this overlaps with {names}."


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

    if is_calendar and not interp.attendee_names:
        fallback_name = _fallback_attendee_name(title, state["message"])
        if fallback_name:
            interp.attendee_names = [fallback_name]

    if interp.attendee_names and not interp.attendee_emails:
        resolved_emails: list[str] = []
        unresolved_names: list[str] = []
        for attendee_name in interp.attendee_names:
            email = find_email_by_name(state["user_email"], attendee_name)
            (resolved_emails if email else unresolved_names).append(email or attendee_name)

        if unresolved_names:
            return {
                "response": ChatResponse(
                    type="clarify", message=f"I don't have {unresolved_names[0]}'s email yet -- what is it?"
                ).model_dump()
            }
        interp.attendee_emails = resolved_emails

    resolved = resolve_instant(interp.time_phrase, now) if interp.time_phrase else None

    if is_calendar:
        missing = _missing_datetime_part(interp.time_phrase, now)
        if missing:
            return {
                "response": ChatResponse(
                    type="clarify", message=f'What {_missing_part_word(missing)} should "{interp.title}" be?'
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
        conflicts = _find_conflicts(state["user_email"], resolved, end, state["timezone"])
        # Whether an attendee was actually resolved (vs. silently dropped,
        # e.g. a name the LLM didn't extract as an attendee at all) must be
        # visible in the confirm step -- otherwise there's no way to notice
        # an invite silently not going out.
        attendee_note = f" with {', '.join(interp.attendee_emails)}" if interp.attendee_emails else ""
        summary_line = (
            f'Create "{interp.title}"{attendee_note} on '
            f'{resolved.strftime("%A %b %d at %I:%M %p")}{_conflict_note(conflicts)}'
        )
        action = "calendar.create"
    else:
        params = {"title": interp.title, "due": _task_due_iso(resolved) if resolved else None}
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
    pending = state.get("pending_disambiguation")

    # A terse follow-up ("3pm", "all", "the second one") gives the model
    # little to classify from, and it can misfire (observed: re-classified
    # an event-disambiguation reply as a task intent). If the reply matches
    # what was ACTUALLY offered last turn, trust THAT turn's original intent
    # over this one's fresh (re)classification, not just its entity type.
    effective_intent = interp.intent
    target = None
    if pending:
        matched = _match_pending_candidate(state["message"], pending["options"], state["timezone"])
        if matched:
            effective_intent = pending["intent"]
            pending_label_key = "summary" if pending["entity_type"] == "event" else "title"
            target = {"id": matched["id"], pending_label_key: matched["name"]}

    entity_type = _ENTITY_TYPE_FOR_INTENT[effective_intent]
    label_key = "summary" if entity_type == "event" else "title"
    noun = "event" if entity_type == "event" else "task"

    if target is None and _mentions_bulk(state["message"]):
        if pending:
            # Re-attach the SAME options rather than drop them -- otherwise
            # telling the user "one at a time" also silently wipes the very
            # context they'd need to answer that with a specific reply.
            pending_noun = "event" if pending["entity_type"] == "event" else "task"
            return {
                "response": ChatResponse(
                    type="clarify",
                    message=f"I can only act on one {pending_noun} at a time right now -- which specific one did you mean?",
                    disambiguation=Disambiguation(**pending),
                ).model_dump()
            }
        return {
            "response": ChatResponse(
                type="clarify",
                message=f"I can only act on one {noun} at a time right now -- which specific one did you mean?",
            ).model_dump()
        }

    if target is None:
        if not interp.target_phrase:
            return {"response": ChatResponse(type="clarify", message=f"Which {noun} do you mean?").model_dump()}

        result = resolve_target(
            entity_type,
            interp.target_phrase,
            state["user_email"],
            include_completed_tasks=effective_intent == "task_reopen",
        )

        if result.status == "not_found":
            return {
                "response": ChatResponse(
                    type="error", message=f'I couldn\'t find "{interp.target_phrase}".'
                ).model_dump()
            }

        if result.status == "ambiguous":
            options = [
                DisambiguationOption(
                    id=c["id"],
                    name=c[label_key],
                    label=_format_candidate(c, entity_type, state["timezone"]),
                    when=c["start"] if entity_type == "event" else c.get("due"),
                )
                for c in result.candidates
            ]
            message = "Which one did you mean -- " + "; ".join(o.label for o in options) + "?"
            return {
                "response": ChatResponse(
                    type="clarify",
                    message=message,
                    disambiguation=Disambiguation(entity_type=entity_type, intent=effective_intent, options=options),
                ).model_dump()
            }

        target = result.candidates[0]
    action = _MUTATE_ACTION[effective_intent]
    request_id = _new_request_id()
    params: dict = {}

    if effective_intent == "calendar_delete":
        summary_line = f'Delete "{target["summary"]}"'
    elif effective_intent == "task_delete":
        summary_line = f'Delete task "{target["title"]}"'
    elif effective_intent == "task_complete":
        summary_line = f'Mark "{target["title"]}" as completed'
    elif effective_intent == "task_reopen":
        summary_line = f'Reopen "{target["title"]}" (mark as not completed)'
    elif effective_intent == "calendar_update":
        new_time = resolve_instant(interp.time_phrase, now) if interp.time_phrase else None
        if interp.time_phrase:
            missing = _missing_datetime_part(interp.time_phrase, now)
            if missing:
                return {
                    "response": ChatResponse(
                        type="clarify",
                        message=f'What {_missing_part_word(missing)} should I move "{target["summary"]}" to?',
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
        conflict_note = ""
        if new_time:
            duration = interp.duration_minutes or DEFAULT_EVENT_DURATION_MINUTES
            conflicts = _find_conflicts(
                state["user_email"], new_time, new_time + timedelta(minutes=duration), state["timezone"], target["id"]
            )
            conflict_note = _conflict_note(conflicts)
        summary_line = f'Move "{target["summary"]}" {change}{conflict_note}'
    else:  # task_update
        new_due = resolve_instant(interp.time_phrase, now) if interp.time_phrase else None
        if new_due:
            params["due"] = _task_due_iso(new_due)
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
