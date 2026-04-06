"""Unit tests for in-memory task store behavior."""

from __future__ import annotations

import pytest

pytest.importorskip("a2a.types")

from a2a.auth.user import User
from a2a.server.context import ServerCallContext
from a2a.types import Task, TaskState, TaskStatus

from .conftest import load_store

STORE = load_store()


class _TestUser(User):
    """Minimal SDK User for test contexts."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def user_name(self) -> str:
        return self._user_id


def _context(user_id: str) -> ServerCallContext:
    return ServerCallContext(
        state={"ha_user_id": user_id},
        user=_TestUser(user_id),
    )


def _task(task_id: str, context_id: str, state: TaskState) -> Task:
    return Task(
        id=task_id,
        context_id=context_id,
        status=TaskStatus(state=state, timestamp="2026-02-27T00:00:00Z"),
    )


@pytest.mark.asyncio
async def test_task_owner_visibility_scoping() -> None:
    """Tasks should only be readable by the creating owner."""
    store = STORE.HaScopedTaskStore()
    await store.save(_task("t-1", "c-1", TaskState.completed), _context("user-1"))

    assert await store.get("t-1", _context("user-1")) is not None
    assert await store.get("t-1", _context("user-2")) is None


@pytest.mark.asyncio
async def test_delete_honors_owner_scope() -> None:
    """Delete should ignore principals that do not own the task."""
    store = STORE.HaScopedTaskStore()
    await store.save(_task("t-1", "c-1", TaskState.working), _context("user-1"))
    await store.delete("t-1", _context("user-2"))
    assert await store.get("t-1", _context("user-1")) is not None
    await store.delete("t-1", _context("user-1"))
    assert await store.get("t-1", _context("user-1")) is None


@pytest.mark.asyncio
async def test_list_tasks_paginates_and_filters() -> None:
    """List should apply owner, status, and paging filters."""
    store = STORE.HaScopedTaskStore()
    await store.save(_task("t-1", "c-1", TaskState.completed), _context("user-1"))
    await store.save(_task("t-2", "c-1", TaskState.working), _context("user-1"))
    await store.save(_task("t-3", "c-2", TaskState.completed), _context("user-2"))

    page, next_token, total = store.list_tasks(
        owner_user_id="user-1",
        context_id="c-1",
        status=TaskState.completed,
        page_size=1,
        page_token="0",
    )

    assert total == 1
    assert len(page) == 1
    assert page[0].id == "t-1"
    assert next_token == ""


def _none_context() -> ServerCallContext:
    """Context with no authenticated user."""
    return ServerCallContext(state={})


@pytest.mark.asyncio
async def test_save_rejects_none_owner() -> None:
    """Save must raise when owner_user_id resolves to None."""
    store = STORE.HaScopedTaskStore()
    with pytest.raises(ValueError, match="authenticated owner"):
        await store.save(_task("t-1", "c-1", TaskState.submitted), _none_context())


@pytest.mark.asyncio
async def test_get_returns_none_for_none_owner() -> None:
    """Get must return None when requesting user is unauthenticated."""
    store = STORE.HaScopedTaskStore()
    await store.save(_task("t-1", "c-1", TaskState.completed), _context("user-1"))
    assert await store.get("t-1", _none_context()) is None


@pytest.mark.asyncio
async def test_delete_noop_for_none_owner() -> None:
    """Delete must silently no-op when requesting user is unauthenticated."""
    store = STORE.HaScopedTaskStore()
    await store.save(_task("t-1", "c-1", TaskState.completed), _context("user-1"))
    await store.delete("t-1", _none_context())
    # Task should still exist for the real owner
    assert await store.get("t-1", _context("user-1")) is not None


def test_list_tasks_empty_for_none_owner() -> None:
    """list_tasks must return empty when owner is None."""
    store = STORE.HaScopedTaskStore()
    page, _next_token, total = store.list_tasks(
        owner_user_id=None,
        context_id=None,
        status=None,
        page_size=50,
        page_token="0",
    )
    assert page == []
    assert total == 0
