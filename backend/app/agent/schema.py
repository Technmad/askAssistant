"""Wire contract from PLAN.md §2 -- decided once, before the graph was
built, so the frontend and backend evolve independently of each other."""

from typing import Literal

from pydantic import BaseModel

ActionType = Literal[
    "calendar.create",
    "calendar.update",
    "calendar.delete",
    "task.create",
    "task.update",
    "task.complete",
    "task.reopen",
    "task.delete",
]


class HistoryTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ReferencedEntity(BaseModel):
    type: Literal["event", "task"]
    id: str
    summary: str


class DisambiguationOption(BaseModel):
    id: str
    name: str
    label: str  # formatted "name (distinguishing time)" shown to the user
    when: str | None = None  # raw start/due ISO timestamp -- lets a reply
    # like "the 2pm one" be resolved by parsing actual times, not by
    # fuzzy-matching text against a differently-formatted label string.


class Disambiguation(BaseModel):
    entity_type: Literal["event", "task"]
    intent: str  # the mutate intent this disambiguation was for (see graph.py
    # _ENTITY_TYPE_FOR_INTENT) -- trusted over a terse follow-up's own
    # (re-)classification, which has little to go on ("3pm", "all") and can
    # misfire on exactly the kind of short reply this field exists to handle.
    options: list[DisambiguationOption]


class ChatRequest(BaseModel):
    message: str
    recent_history: list[HistoryTurn] = []
    last_referenced_entity: ReferencedEntity | None = None
    # Echoed back from the previous turn's ChatResponse.disambiguation so a
    # reply like "the second one" or "the 2pm one" can be matched against
    # what was actually offered, not re-derived from scratch (PLAN.md's
    # stateless design means the server has no memory of its own).
    pending_disambiguation: Disambiguation | None = None
    now: str  # client's local wall-clock time, ISO 8601, naive
    timezone: str  # IANA name, e.g. "Asia/Kolkata"


class ProposedAction(BaseModel):
    request_id: str
    action: ActionType
    entity_id: str | None = None  # None for create; set for update/complete/delete
    params: dict


class ChatResponse(BaseModel):
    type: Literal["clarify", "propose", "result", "error"]
    message: str
    proposed_action: ProposedAction | None = None
    # Present on "propose"/"result" so the client can set last_referenced_entity
    # for the next turn's pronoun resolution ("move it to Monday").
    referenced_entity: ReferencedEntity | None = None
    # Present on "clarify" when the message lists multiple same-named
    # candidates -- client echoes this back as pending_disambiguation.
    disambiguation: Disambiguation | None = None


class ExecuteRequest(BaseModel):
    proposed_action: ProposedAction
    timezone: str  # IANA name -- so the result message reports back in the
    # user's own local time, not whatever offset Google's API returned it in.


class ExecuteResponse(BaseModel):
    type: Literal["result", "error"]
    message: str
    referenced_entity: ReferencedEntity | None = None
