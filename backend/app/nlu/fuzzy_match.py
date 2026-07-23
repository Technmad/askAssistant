"""Shared fuzzy string scoring -- used by resolve_target (matching a query
against event/task titles) and contacts lookup (matching a name against
Google Contacts), so both use the identical, tested scoring rule."""

from difflib import SequenceMatcher


def score(query: str, text: str) -> float:
    query, text = query.lower(), text.lower()
    if query in text:
        # A short query ("dentist") naming multiple longer titles ("Dentist",
        # "Dentist follow-up") should be equally plausible against all of
        # them -- SequenceMatcher's whole-string ratio would unfairly punish
        # the longer title just for having more trailing text.
        return 1.0
    return SequenceMatcher(None, query, text).ratio()
