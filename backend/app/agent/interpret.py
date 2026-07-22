"""LLM step: turns natural language into a structured intent + raw slots.

This is the ONLY place an LLM is involved in the whole request/response
cycle. It never resolves dates, never picks an entity ID, and never
decides anything reliability-critical -- it just extracts what the user
said, in their own words, for the deterministic graph nodes downstream
(datetime_resolver, resolve_target) to act on.
"""

import json
from dataclasses import dataclass, field

from groq import Groq

from ..config import settings
from .schema import HistoryTurn, ReferencedEntity

_client = Groq(api_key=settings.groq_api_key)

INTENTS = [
    "calendar_create",
    "calendar_update",
    "calendar_delete",
    "calendar_read",
    "task_create",
    "task_update",
    "task_complete",
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
                        "Event or task title, if creating one or renaming an existing one. If the "
                        "user didn't state an explicit title but the intent is clear from context "
                        "(e.g. 'schedule a meeting with John' or 'set up a call with the design "
                        "team'), synthesize a short, sensible title yourself, e.g. 'Meeting with "
                        "John' or 'Call with design team'. Only leave this null if there's truly no "
                        "reasonable title to infer."
                    ),
                },
                "time_phrase": {
                    "type": ["string", "null"],
                    "description": (
                        "A phrase naming when a single event/task should happen, e.g. 'tomorrow "
                        "3pm', 'next Monday morning'. Must include BOTH a date reference (today/"
                        "tomorrow/a weekday) AND a time-of-day if either was mentioned anywhere in "
                        "this conversation -- if the date was given in an earlier turn (e.g. "
                        "assistant asked 'what time?' after the user said 'tomorrow') and the "
                        "user's latest message only supplies the time (e.g. '3pm'), COMBINE them "
                        "into one phrase covering both, e.g. 'tomorrow 3pm'. Do not resolve the "
                        "phrase into an actual date yourself -- just make sure it's complete."
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
                        "meeting'. If the user used a pronoun ('it', 'that'), resolve it using the "
                        "last-referenced entity given in context and describe THAT entity here instead."
                    ),
                },
                "duration_minutes": {
                    "type": ["integer", "null"],
                    "description": "Meeting duration in minutes, only if the user stated or implied one.",
                },
                "attendee_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Names of people to invite, exactly as the user said them (e.g. 'John'). Empty if none mentioned.",
                },
                "attendee_emails": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Email addresses for attendees, ONLY if the user (or an earlier turn) already "
                        "gave an actual email address. Never guess or invent an email from a name."
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
    "use intent=\"unclear\"."
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

    response = _client.chat.completions.create(
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
