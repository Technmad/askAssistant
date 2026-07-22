"""Pure-logic relative datetime resolution (PLAN.md §3) -- no I/O, no LLM.

The agent's LLM step only extracts a raw phrase like "tomorrow 3pm" or
"next Monday morning" from the user's message; everything about what that
phrase actually MEANS is decided here, deterministically, so it can be
tested exactly and never drifts turn to turn.

Callers always pass `now` as the client's own current local time (naive,
already in the user's wall-clock) -- this module never reads the system
clock or a timezone database itself.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

_TIME_OF_DAY_DEFAULTS = {
    "morning": time(9, 0),
    "afternoon": time(14, 0),
    "evening": time(18, 0),
    "night": time(20, 0),
}

# 12-hour form ("3pm", "3:30 pm", "9 am") or 24-hour form ("15:00", "09:30")
_EXPLICIT_TIME_RE = re.compile(
    r"\b(?P<hour12>1[0-2]|0?[1-9])(:(?P<minute12>[0-5][0-9]))?\s*(?P<ampm>am|pm)\b"
    r"|\b(?P<hour24>[01]?[0-9]|2[0-3]):(?P<minute24>[0-5][0-9])\b",
    re.IGNORECASE,
)

_WEEKDAY_RE = re.compile(
    r"\b(?P<prefix>next|this)?\s*(?P<weekday>" + "|".join(WEEKDAYS) + r")\b",
    re.IGNORECASE,
)


@dataclass
class ResolvedRange:
    start: datetime
    end: datetime


def extract_time_of_day(phrase: str) -> time | None:
    """Explicit clock time takes priority over vague day-part words."""
    match = _EXPLICIT_TIME_RE.search(phrase)
    if match:
        if match.group("hour24") is not None:
            return time(int(match.group("hour24")), int(match.group("minute24")))
        hour = int(match.group("hour12"))
        minute = int(match.group("minute12") or 0)
        ampm = match.group("ampm").lower()
        if ampm == "pm" and hour != 12:
            hour += 12
        if ampm == "am" and hour == 12:
            hour = 0
        return time(hour, minute)

    lowered = phrase.lower()
    for keyword, default_time in _TIME_OF_DAY_DEFAULTS.items():
        if keyword in lowered:
            return default_time

    return None


def parse_relative_date(phrase: str, now: datetime) -> date | None:
    """Resolves "today"/"tomorrow"/weekday-name references to a concrete
    date. Returns None if the phrase names no recognizable date at all."""
    lowered = phrase.lower()

    if "tomorrow" in lowered:
        return (now + timedelta(days=1)).date()
    if "today" in lowered or "tonight" in lowered:
        return now.date()

    match = _WEEKDAY_RE.search(lowered)
    if not match:
        return None

    weekday_index = WEEKDAYS.index(match.group("weekday"))
    prefix = match.group("prefix")
    days_until = (weekday_index - now.weekday()) % 7

    if days_until == 0 and prefix == "next":
        # "next Friday" said on a Friday unambiguously means next week.
        # Bare "Friday" or "this Friday" said on a Friday means today --
        # see resolve_instant for the same-day-but-already-passed check.
        days_until = 7

    return (now + timedelta(days=days_until)).date()


def resolve_instant(phrase: str, now: datetime) -> datetime | None:
    """A single point in time for scheduling (create/move an event, set a
    task's due date). Returns None if no date could be parsed at all --
    the caller should treat that as missing information, not guess."""
    resolved_date = parse_relative_date(phrase, now)
    if resolved_date is None:
        return None

    resolved_time = extract_time_of_day(phrase)
    if resolved_time is None:
        # No time-of-day mentioned at all -- caller decides whether that's
        # acceptable (fine for a task due-date) or needs a clarifying
        # question (required for a calendar event).
        return datetime.combine(resolved_date, time(0, 0))

    candidate = datetime.combine(resolved_date, resolved_time)

    # Bare/"this"-prefixed weekday that resolved to *today*: if that time
    # has already passed, roll forward a week rather than propose the past.
    if resolved_date == now.date() and candidate <= now:
        candidate += timedelta(days=7)

    return candidate


def resolve_range(phrase: str, now: datetime) -> ResolvedRange | None:
    """A date range for read queries ("what's this week look like").
    "This week" = today through the upcoming Sunday (not Monday-of-this-week
    through Sunday) -- past days in the current week aren't useful in a
    read, so the range starts from now rather than the calendar week start."""
    lowered = phrase.lower()
    today_start = datetime.combine(now.date(), time(0, 0))

    if "this week" in lowered:
        days_to_sunday = 6 - now.weekday()
        end = datetime.combine(now.date() + timedelta(days=days_to_sunday), time(23, 59, 59))
        return ResolvedRange(start=today_start, end=end)

    if "next week" in lowered:
        days_to_next_monday = 7 - now.weekday()
        start = datetime.combine(now.date() + timedelta(days=days_to_next_monday), time(0, 0))
        end = start + timedelta(days=6, hours=23, minutes=59, seconds=59)
        return ResolvedRange(start=start, end=end)

    if "today" in lowered or "tonight" in lowered:
        return ResolvedRange(start=today_start, end=datetime.combine(now.date(), time(23, 59, 59)))

    if "tomorrow" in lowered:
        tomorrow = now.date() + timedelta(days=1)
        return ResolvedRange(
            start=datetime.combine(tomorrow, time(0, 0)),
            end=datetime.combine(tomorrow, time(23, 59, 59)),
        )

    return None
