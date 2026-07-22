from ..google_clients import tasks_client

DEFAULT_TASKLIST = "@default"


def _serialize(item: dict) -> dict:
    return {
        "id": item["id"],
        "title": item.get("title", "(no title)"),
        "due": item.get("due"),
        "status": item.get("status", "needsAction"),
    }


def list_tasks(
    user_email: str,
    show_completed: bool = False,
    max_results: int = 50,
    due_min: str | None = None,
    due_max: str | None = None,
) -> list[dict]:
    service = tasks_client(user_email)
    kwargs = {"tasklist": DEFAULT_TASKLIST, "showCompleted": show_completed, "maxResults": max_results}
    if due_min is not None:
        kwargs["dueMin"] = due_min
    if due_max is not None:
        kwargs["dueMax"] = due_max
    result = service.tasks().list(**kwargs).execute()
    return [_serialize(item) for item in result.get("items", [])]


def get_task(user_email: str, task_id: str) -> dict:
    service = tasks_client(user_email)
    item = service.tasks().get(tasklist=DEFAULT_TASKLIST, task=task_id).execute()
    return _serialize(item)


def create_task(user_email: str, title: str, due: str | None = None) -> dict:
    service = tasks_client(user_email)
    body: dict = {"title": title}
    if due is not None:
        body["due"] = due
    created = service.tasks().insert(tasklist=DEFAULT_TASKLIST, body=body).execute()
    return _serialize(created)


def update_task(
    user_email: str,
    task_id: str,
    title: str | None = None,
    due: str | None = None,
    status: str | None = None,
) -> dict:
    service = tasks_client(user_email)
    body: dict = {}
    if title is not None:
        body["title"] = title
    if due is not None:
        body["due"] = due
    if status is not None:
        body["status"] = status

    updated = service.tasks().patch(tasklist=DEFAULT_TASKLIST, task=task_id, body=body).execute()
    return _serialize(updated)


def complete_task(user_email: str, task_id: str) -> dict:
    return update_task(user_email, task_id, status="completed")


def delete_task(user_email: str, task_id: str) -> None:
    service = tasks_client(user_email)
    service.tasks().delete(tasklist=DEFAULT_TASKLIST, task=task_id).execute()
