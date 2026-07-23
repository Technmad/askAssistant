"""Shared read -> match -> confirm resolution, used identically for
Calendar events and Tasks so Tasks can't quietly become the less-tested
path behind Calendar."""

from dataclasses import dataclass, field
from typing import Literal

from ..nlu.fuzzy_match import score as fuzzy_score
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


def resolve_target(
    entity_type: EntityType, query: str, user_email: str, include_completed_tasks: bool = False
) -> ResolveResult:
    label_key = _LABEL_KEY[entity_type]
    items = (
        calendar_service.list_events(user_email)
        if entity_type == "event"
        else tasks_service.list_tasks(user_email, show_completed=include_completed_tasks)
    )

    scored = [
        (score, item)
        for item in items
        if (score := fuzzy_score(query, item[label_key])) >= _MATCH_THRESHOLD
    ]
    scored.sort(key=lambda pair: pair[0], reverse=True)

    if not scored:
        return ResolveResult(status="not_found")

    top_score = scored[0][0]
    top_matches = [item for score, item in scored if score >= top_score - _AMBIGUITY_MARGIN]

    if len(top_matches) == 1:
        return ResolveResult(status="match", candidates=top_matches)
    return ResolveResult(status="ambiguous", candidates=top_matches[:5])
