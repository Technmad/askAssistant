"""Read-only Google Contacts lookup so a named attendee ("John") resolves
to an email automatically when they're an existing contact, falling back
to asking only when they genuinely aren't."""

from ..google_clients import people_client

# Requires effectively a full word-for-word match (see _name_score) --
# inviting the wrong person to a meeting is a worse mistake than a
# slightly-off calendar read, so this only auto-resolves a confident,
# unambiguous match. Found live: "priyanka" scored 0.57 against
# "Priyadharsini" under plain character-overlap scoring (shared "priya-"
# prefix), well above a naive threshold, and silently invited the wrong
# real contact. Word-based matching below fixes the root cause; this
# threshold is now a fraction of whole query WORDS matched, not characters.
_MATCH_THRESHOLD = 1.0
_AMBIGUITY_MARGIN = 0.05
_MIN_TYPO_WORD_LEN = 4  # below this, even a 1-letter edit changes too much of the word to trust


def _edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[-1]


def _word_matches(word: str, contact_word: str) -> bool:
    if word == contact_word:
        return True
    # Ratio-based scoring (e.g. SequenceMatcher) was found live to conflate a
    # genuine single-letter typo ("Rukum" vs "Rukam") with two DIFFERENT real
    # names of different lengths ("amit" vs "asmita" also scores 0.8 on that
    # scale, and silently invited the wrong real contact to a meeting). A
    # same-length, single-character substitution is a much narrower, safer
    # definition of "typo" -- it does not fire on insertions/deletions, which
    # is exactly what turns one short name into a different, longer one.
    if len(word) != len(contact_word) or len(word) < _MIN_TYPO_WORD_LEN:
        return False
    return _edit_distance(word, contact_word) <= 1


def _name_score(query: str, contact_name: str) -> float:
    """Word-based, not character-overlap based. Character-fuzzy scoring
    conflates "shares a prefix" with "is the same name" -- every word in
    the query must closely match some word in the contact's full name, not
    just overlap when both strings are flattened and compared as a whole."""
    query_words = query.lower().split()
    contact_words = contact_name.lower().split()
    if not query_words:
        return 0.0
    matched = sum(1 for word in query_words if any(_word_matches(word, cw) for cw in contact_words))
    return matched / len(query_words)


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
    scored = [(_name_score(name, c["name"]), c) for c in _list_contacts(user_email)]
    scored.sort(key=lambda pair: pair[0], reverse=True)

    if not scored or scored[0][0] < _MATCH_THRESHOLD:
        return None
    # Two similarly-named contacts is safer to punt on than to silently
    # guess -- fall back to asking rather than risk inviting the wrong person.
    if len(scored) > 1 and scored[1][0] >= scored[0][0] - _AMBIGUITY_MARGIN:
        return None

    return scored[0][1]["email"]
