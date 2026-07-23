"""LLM step: turns natural language into a structured intent + raw slots.

This is the ONLY place an LLM is involved in the whole request/response
cycle. It never resolves dates, never picks an entity ID, and never
decides anything reliability-critical -- it just extracts what the user
said, in their own words, for the deterministic graph nodes downstream
(datetime_resolver, resolve_target) to act on.
"""

import json
from dataclasses import dataclass, field

from ..config import settings
from ..groq_client import groq_client
from .schema import HistoryTurn, ReferencedEntity

INTENTS = [
    "calendar_create",
    "calendar_update",
    "calendar_delete",
    "calendar_read",
    "task_create",
    "task_update",
    "task_complete",
    "task_reopen",  # "unmark", "reopen", "mark as not done", "undo completing"
    "task_delete",
    "task_read",
    "chitchat",
    "unclear",
]

_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "interpret_request",
        "description": "Interpret the user's calendar/task assistant request into a structured intent.",
        "parameters": {
            "type": "object",
            "properties": {
                "intent": {"type": "string", "enum": INTENTS},
                "title": {
                    "type": ["string", "null"],
                    "description": (
                        "For a CREATE: the event/task title. If the user didn't state an explicit "
                        "title but the intent is clear from context (e.g. 'schedule a meeting with "
                        "John'), synthesize a short, sensible one yourself, e.g. 'Meeting with John'. "
                        "For an UPDATE/COMPLETE/DELETE of an EXISTING item: leave this null unless the "
                        "user is EXPLICITLY asking to rename/retitle it to something new (e.g. 'rename "
                        "my dentist appointment to Dental checkup'). Merely referring to an existing "
                        "item by a descriptive phrase ('my submit budget task', 'the dentist "
                        "appointment') is NOT a rename request -- that phrase belongs in target_phrase "
                        "only, never copied into title as well. A CREATE is only a continuation of an "
                        "earlier turn's title/attendee when it's directly answering a still-OPEN "
                        "clarifying question about that same unfinished request. Once an assistant "
                        "message starting with 'Created' has appeared, that request is done -- a later, "
                        "vague CREATE ('schedule a meeting tomorrow') that names no one and nothing is a "
                        "brand-new request with an unknown title, never a reuse of an earlier, already-"
                        "completed one, even if it sounds similar."
                    ),
                },
                "time_phrase": {
                    "type": ["string", "null"],
                    "description": (
                        "A phrase naming when a single event/task should happen, e.g. 'tomorrow "
                        "3pm', 'next Monday morning'. Must include BOTH a date reference (today/"
                        "tomorrow/a weekday) AND a time-of-day if EITHER was mentioned ANYWHERE "
                        "earlier in this conversation, even if the current message only supplies "
                        "the other half. This works in BOTH directions -- e.g. the date came first "
                        "('tomorrow' -> assistant asked 'what time?' -> user says '3pm': combine "
                        "into 'tomorrow 3pm'), OR the time came first ('12pm' -> assistant asked "
                        "'what day?' -> user says 'day after tomorrow': combine into 'day after "
                        "tomorrow 12pm'). Always look back through the WHOLE conversation for the "
                        "missing half, not just the most recent assistant question. Do not resolve "
                        "the phrase into an actual date yourself -- just make sure it's complete."
                    ),
                },
                "range_phrase": {
                    "type": ["string", "null"],
                    "description": "The user's own words naming a date range for a read query, e.g. 'this week', 'today'.",
                },
                "target_phrase": {
                    "type": ["string", "null"],
                    "description": (
                        "A short phrase identifying which EXISTING event/task is being updated, "
                        "completed, or deleted, e.g. 'dentist appointment', 'grocery task', 'Friday "
                        "meeting'. If the user used a pronoun ('it', 'that') OR gave a bare command "
                        "with NO explicit name at all ('unmark', 'undo that', 'reopen it', 'delete "
                        "it'), resolve it using the last-referenced entity given in context and "
                        "describe THAT entity here instead. NEVER invent or guess a different item's "
                        "name when no name was actually given -- if there's no last-referenced entity "
                        "to fall back on either, leave this null so the user gets asked to clarify."
                    ),
                },
                "duration_minutes": {
                    "type": ["integer", "null"],
                    "description": "Meeting duration in minutes, only if the user stated or implied one.",
                },
                "attendee_names": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "description": (
                        "Names of people to invite, exactly as the user said them (e.g. 'John'). Null "
                        "or empty if none mentioned in THIS request. Only carry a name over from an "
                        "earlier turn if this message is directly answering a still-OPEN clarifying "
                        "question about that same unfinished request (e.g. the assistant just asked "
                        "for their email). Once that request has been completed (an assistant message "
                        "starting with 'Created' appeared), a later CREATE that names no one is a "
                        "brand-new request with no attendees -- never reuse an earlier, already-invited "
                        "person just because the new request also mentions 'a meeting'."
                    ),
                },
                "attendee_emails": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "description": (
                        "Email addresses for attendees, ONLY if the user (or an earlier turn) already "
                        "gave an actual email address. Never guess or invent an email from a name. "
                        "Null or empty if none given."
                    ),
                },
            },
            "required": ["intent"],
        },
    },
}

SYSTEM_PROMPT = (
    "You are the natural-language understanding layer of a Calendar/Tasks assistant. "
    "Your ONLY job is to call interpret_request with a structured breakdown of the user's "
    "message. You do not resolve dates, you do not invent IDs, and you do not decide anything "
    "about scheduling conflicts -- a separate deterministic system handles all of that. Extract "
    "only what the user actually said. If the user's message is a greeting, thanks, or unrelated "
    "to calendar/tasks, use intent=\"chitchat\". If you genuinely cannot tell what the user wants, "
    "use intent=\"unclear\". An action verb (delete/cancel/remove, complete/mark done, update/"
    "reschedule/move/rename, unmark/reopen) followed by ANY noun phrase is always that action's "
    "intent, even if the noun phrase itself looks like a technical or generic term (e.g. 'sync', "
    "'call', 'meeting', 'task') -- the event/task's title can be any word at all, so never let the "
    "title's wording push you toward chitchat or unclear."
)


@dataclass
class Interpretation:
    intent: str
    title: str | None = None
    time_phrase: str | None = None
    range_phrase: str | None = None
    target_phrase: str | None = None
    duration_minutes: int | None = None
    attendee_names: list[str] = field(default_factory=list)
    attendee_emails: list[str] = field(default_factory=list)


def interpret(
    message: str,
    recent_history: list[HistoryTurn],
    last_referenced_entity: ReferencedEntity | None,
    now: str,
    timezone: str,
) -> Interpretation:
    context_lines = [f"Current time: {now} ({timezone})"]
    if last_referenced_entity:
        context_lines.append(
            f'Last referenced {last_referenced_entity.type}: "{last_referenced_entity.summary}" '
            "(resolve the user's 'it'/'that' to this if applicable)"
        )

    messages = [{"role": "system", "content": SYSTEM_PROMPT + "\n\n" + "\n".join(context_lines)}]
    for turn in recent_history[-10:]:
        messages.append({"role": turn.role, "content": turn.content})
    messages.append({"role": "user", "content": message})

    response = groq_client.chat.completions.create(
        model=settings.groq_model,
        messages=messages,
        tools=[_TOOL_SCHEMA],
        tool_choice={"type": "function", "function": {"name": "interpret_request"}},
        temperature=0,
    )

    tool_call = response.choices[0].message.tool_calls[0]
    args = json.loads(tool_call.function.arguments)

    return Interpretation(
        intent=args.get("intent", "unclear"),
        title=args.get("title"),
        time_phrase=args.get("time_phrase"),
        range_phrase=args.get("range_phrase"),
        target_phrase=args.get("target_phrase"),
        duration_minutes=args.get("duration_minutes"),
        attendee_names=args.get("attendee_names") or [],
        attendee_emails=args.get("attendee_emails") or [],
    )
