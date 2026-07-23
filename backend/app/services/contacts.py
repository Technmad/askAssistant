"""Read-only Google Contacts lookup so a named attendee ("John") resolves
to an email automatically when they're an existing contact, falling back
to asking only when they genuinely aren't (PLAN.md §5)."""

from ..google_clients import people_client
from ..nlu.fuzzy_match import score as fuzzy_score

# Stricter than event/task matching (0.35) -- inviting the wrong person to
# a meeting is a worse mistake than a slightly-off calendar read, so this
# only auto-resolves a confident, unambiguous match.
_MATCH_THRESHOLD = 0.5
_AMBIGUITY_MARGIN = 0.05


def _extract(person: dict) -> dict | None:
    names = person.get("names") or []
    emails = person.get("emailAddresses") or []
    if names and emails:
        return {"name": names[0]["displayName"], "email": emails[0]["value"]}
    return None


def _list_saved_contacts(service) -> list[dict]:
    contacts: list[dict] = []
    page_token = None
    while True:
        response = (
            service.people()
            .connections()
            .list(
                resourceName="people/me",
                personFields="names,emailAddresses",
                pageSize=200,
                pageToken=page_token,
            )
            .execute()
        )
        contacts.extend(c for p in response.get("connections", []) if (c := _extract(p)))
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return contacts


def _list_other_contacts(service) -> list[dict]:
    # "Other contacts" -- people auto-suggested from Gmail history who were
    # never explicitly saved. A separate API surface (and OAuth scope) from
    # saved contacts, but just as likely to be who a user means by name.
    contacts: list[dict] = []
    page_token = None
    while True:
        response = (
            service.otherContacts()
            .list(readMask="names,emailAddresses", pageSize=200, pageToken=page_token)
            .execute()
        )
        contacts.extend(c for p in response.get("otherContacts", []) if (c := _extract(p)))
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return contacts


def _list_contacts(user_email: str) -> list[dict]:
    service = people_client(user_email)
    return _list_saved_contacts(service) + _list_other_contacts(service)


def find_email_by_name(user_email: str, name: str) -> str | None:
    scored = [(fuzzy_score(name, c["name"]), c) for c in _list_contacts(user_email)]
    scored.sort(key=lambda pair: pair[0], reverse=True)

    if not scored or scored[0][0] < _MATCH_THRESHOLD:
        return None
    # Two similarly-named contacts is safer to punt on than to silently
    # guess -- fall back to asking rather than risk inviting the wrong person.
    if len(scored) > 1 and scored[1][0] >= scored[0][0] - _AMBIGUITY_MARGIN:
        return None

    return scored[0][1]["email"]
