"""Shared read -> match -> confirm resolution, used identically for
Calendar events and Tasks (PLAN.md §4) so Tasks can't quietly become
the less-tested path behind Calendar."""

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Literal

from . import calendar as calendar_service
from . import tasks as tasks_service

EntityType = Literal["event", "task"]
Status = Literal["match", "ambiguous", "not_found"]

_LABEL_KEY = {"event": "summary", "task": "title"}
_MATCH_THRESHOLD = 0.35
_AMBIGUITY_MARGIN = 0.05  # candidates within this of the top score are all "the same match quality"


@dataclass
class ResolveResult:
    status: Status
    candidates: list[dict] = field(default_factory=list)  # 1 item if match, 2+ if ambiguous, [] if not_found


def _score(query: str, text: str) -> float:
    query, text = query.lower(), text.lower()
    if query in text:
        # A short query ("dentist") naming multiple longer titles ("Dentist",
        # "Dentist follow-up") should be equally plausible against all of
        # them -- SequenceMatcher's whole-string ratio would unfairly punish
        # the longer title just for having more trailing text.
        return 1.0
    return SequenceMatcher(None, query, text).ratio()


def resolve_target(entity_type: EntityType, query: str, user_email: str) -> ResolveResult:
    label_key = _LABEL_KEY[entity_type]
    items = (
        calendar_service.list_events(user_email)
        if entity_type == "event"
        else tasks_service.list_tasks(user_email)
    )

    scored = [
        (score, item)
        for item in items
        if (score := _score(query, item[label_key])) >= _MATCH_THRESHOLD
    ]
    scored.sort(key=lambda pair: pair[0], reverse=True)

    if not scored:
        return ResolveResult(status="not_found")

    top_score = scored[0][0]
    top_matches = [item for score, item in scored if score >= top_score - _AMBIGUITY_MARGIN]

    if len(top_matches) == 1:
        return ResolveResult(status="match", candidates=top_matches)
    return ResolveResult(status="ambiguous", candidates=top_matches[:5])
