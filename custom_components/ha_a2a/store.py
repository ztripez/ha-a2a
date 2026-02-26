"""A2A SDK task store adapters with Home Assistant principal scoping."""

from __future__ import annotations

from dataclasses import dataclass

from a2a.server.context import ServerCallContext
from a2a.server.tasks.task_store import TaskStore
from a2a.types import Task, TaskState


@dataclass(slots=True)
class _ScopedTaskRecord:
    """Stored task with owner principal metadata."""

    owner_user_id: str | None
    task: Task


def _owner_from_context(context: ServerCallContext | None) -> str | None:
    """Resolve Home Assistant user id from call context state."""
    if context is None:
        return None

    owner_user_id = context.state.get("ha_user_id")
    if isinstance(owner_user_id, str):
        return owner_user_id

    return None


class HaScopedTaskStore(TaskStore):
    """TaskStore implementation that scopes tasks to HA principals."""

    def __init__(self) -> None:
        """Initialize empty in-memory task storage."""
        self._tasks: dict[str, _ScopedTaskRecord] = {}

    async def save(self, task: Task, context: ServerCallContext | None = None) -> None:
        """Persist or update one task record for the active principal."""
        owner_user_id = _owner_from_context(context)
        existing = self._tasks.get(task.id)

        if existing is None:
            self._tasks[task.id] = _ScopedTaskRecord(
                owner_user_id=owner_user_id,
                task=task.model_copy(deep=True),
            )
            return

        if owner_user_id is not None and existing.owner_user_id != owner_user_id:
            return

        existing.task = task.model_copy(deep=True)

    async def get(
        self, task_id: str, context: ServerCallContext | None = None
    ) -> Task | None:
        """Load one task only if visible to the active principal."""
        record = self._tasks.get(task_id)
        if record is None:
            return None

        owner_user_id = _owner_from_context(context)
        if record.owner_user_id != owner_user_id:
            return None

        return record.task.model_copy(deep=True)

    async def delete(
        self, task_id: str, context: ServerCallContext | None = None
    ) -> None:
        """Delete a task when visible to the active principal."""
        record = self._tasks.get(task_id)
        if record is None:
            return

        owner_user_id = _owner_from_context(context)
        if record.owner_user_id != owner_user_id:
            return

        del self._tasks[task_id]

    def list_tasks(
        self,
        *,
        owner_user_id: str | None,
        context_id: str | None,
        status: TaskState | None,
        page_size: int,
        page_token: str,
    ) -> tuple[list[Task], str, int]:
        """List principal-visible tasks for local `tasks/list` extension."""
        filtered: list[Task] = []
        for record in self._tasks.values():
            task = record.task
            if record.owner_user_id != owner_user_id:
                continue
            if context_id is not None and task.context_id != context_id:
                continue
            if status is not None and task.status.state != status:
                continue
            filtered.append(task.model_copy(deep=True))

        filtered.sort(
            key=lambda task: task.status.timestamp or "",
            reverse=True,
        )

        start = int(page_token)
        end = start + page_size
        page = filtered[start:end]
        next_page_token = "" if end >= len(filtered) else str(end)
        return page, next_page_token, len(filtered)
