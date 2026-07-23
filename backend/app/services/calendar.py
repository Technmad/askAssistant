from datetime import datetime, timedelta, timezone

from ..google_clients import calendar_client


def _serialize(item: dict) -> dict:
    return {
        "id": item["id"],
        "summary": item.get("summary", "(no title)"),
        "start": item["start"].get("dateTime", item["start"].get("date")),
        "end": item["end"].get("dateTime", item["end"].get("date")),
    }


def list_events(
    user_email: str,
    time_min: str | None = None,
    time_max: str | None = None,
    max_results: int = 50,
) -> list[dict]:
    service = calendar_client(user_email)
    if time_min is None:
        # include a day of lookback so "today"/"this morning" references
        # that already started aren't invisible to matching
        time_min = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

    kwargs = {
        "calendarId": "primary",
        "timeMin": time_min,
        "maxResults": max_results,
        "singleEvents": True,
        "orderBy": "startTime",
    }
    if time_max is not None:
        kwargs["timeMax"] = time_max

    result = service.events().list(**kwargs).execute()
    return [_serialize(item) for item in result.get("items", [])]


def get_event(user_email: str, event_id: str) -> dict:
    service = calendar_client(user_email)
    item = service.events().get(calendarId="primary", eventId=event_id).execute()
    return _serialize(item)


def create_event(
    user_email: str,
    summary: str,
    start: str,
    end: str,
    time_zone: str,
    attendees: list[str] | None = None,
) -> dict:
    service = calendar_client(user_email)
    body = {
        "summary": summary,
        "start": {"dateTime": start, "timeZone": time_zone},
        "end": {"dateTime": end, "timeZone": time_zone},
    }
    if attendees:
        body["attendees"] = [{"email": email} for email in attendees]

    # Google does NOT email attendees by default -- sendUpdates="all" is
    # required or they're silently added to the guest list with no actual
    # notification, defeating the point of inviting them at all.
    created = service.events().insert(calendarId="primary", body=body, sendUpdates="all").execute()
    return _serialize(created)


def update_event(
    user_email: str,
    event_id: str,
    summary: str | None = None,
    start: str | None = None,
    end: str | None = None,
    time_zone: str | None = None,
) -> dict:
    service = calendar_client(user_email)
    body: dict = {}
    if summary is not None:
        body["summary"] = summary
    if start is not None:
        body["start"] = {"dateTime": start, "timeZone": time_zone}
    if end is not None:
        body["end"] = {"dateTime": end, "timeZone": time_zone}

    updated = service.events().patch(calendarId="primary", eventId=event_id, body=body, sendUpdates="all").execute()
    return _serialize(updated)


def delete_event(user_email: str, event_id: str) -> None:
    service = calendar_client(user_email)
    # sendUpdates="all" here too -- an attendee should be notified a meeting
    # is cancelled, not left to discover it by finding an empty calendar slot.
    service.events().delete(calendarId="primary", eventId=event_id, sendUpdates="all").execute()
