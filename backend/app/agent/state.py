from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    # request inputs (see ChatRequest)
    message: str
    recent_history: list[dict]
    last_referenced_entity: dict | None
    now: str
    timezone: str
    user_email: str

    # populated by interpret_node
    interpretation: Any  # Interpretation

    # final ChatResponse, as a dict
    response: dict
