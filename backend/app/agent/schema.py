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
    "task.delete",
]


class HistoryTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ReferencedEntity(BaseModel):
    type: Literal["event", "task"]
    id: str
    summary: str


class ChatRequest(BaseModel):
    message: str
    recent_history: list[HistoryTurn] = []
    last_referenced_entity: ReferencedEntity | None = None
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


class ExecuteRequest(BaseModel):
    proposed_action: ProposedAction


class ExecuteResponse(BaseModel):
    type: Literal["result", "error"]
    message: str
    referenced_entity: ReferencedEntity | None = None
