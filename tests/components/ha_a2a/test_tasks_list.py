"""Tests for the local ``tasks/list`` extension handler.

Exercises the ``_handle_tasks_list`` function end-to-end through
the store, verifying filtering, pagination, history truncation,
and artifact exclusion.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("a2a.types")

from a2a.auth.user import User  # noqa: E402
from a2a.server.context import ServerCallContext  # noqa: E402
from a2a.types import (  # noqa: E402
    Artifact,
    Message,
    Part,
    Task,
    TaskState,
    TaskStatus,
    TextPart,
)

from .conftest import load_http, load_store  # noqa: E402

STORE = load_store()
HTTP = load_http()


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


def _task(
    task_id: str,
    context_id: str,
    state: TaskState,
    *,
    history: list[Message] | None = None,
    artifacts: list[Artifact] | None = None,
) -> Task:
    return Task(
        id=task_id,
        context_id=context_id,
        status=TaskStatus(state=state, timestamp="2026-02-28T00:00:00Z"),
        history=history,
        artifacts=artifacts,
    )


def _make_message(text: str, role: str = "agent") -> Message:
    return Message(
        role=role,
        parts=[Part(root=TextPart(text=text))],
        message_id=f"msg-{text}",
    )


def _make_artifact(name: str) -> Artifact:
    return Artifact(
        artifact_id=f"art-{name}",
        parts=[Part(root=TextPart(text=f"artifact-{name}"))],
        name=name,
    )


async def _populate_store(store):
    """Add a mix of tasks for testing."""
    ctx_a = _context("user-a")
    ctx_b = _context("user-b")
    await store.save(
        _task(
            "t-1",
            "c-1",
            TaskState.completed,
            history=[_make_message("m1"), _make_message("m2"), _make_message("m3")],
            artifacts=[_make_artifact("art1")],
        ),
        ctx_a,
    )
    await store.save(
        _task(
            "t-2",
            "c-1",
            TaskState.working,
            history=[_make_message("m4")],
        ),
        ctx_a,
    )
    await store.save(
        _task("t-3", "c-2", TaskState.completed),
        ctx_b,
    )
    return store


def _call_tasks_list(store, body: dict, user_id: str = "user-a"):
    """Invoke _handle_tasks_list and parse the JSON response."""
    from .conftest import _ensure_ha_stubs, _load_module, load_const

    _ensure_ha_stubs()
    load_const()

    # Build a minimal runtime-like object with just a task_store
    class FakeRuntime:
        def __init__(self, task_store):
            self.task_store = task_store

    runtime = FakeRuntime(store)
    ctx = _context(user_id)

    resp = HTTP._handle_tasks_list(runtime, body, ctx)
    return json.loads(resp.body)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTasksListFiltering:
    """Test owner scoping, status filtering, and context_id filtering."""

    @pytest.mark.asyncio
    async def test_owner_scoping(self) -> None:
        store = await _populate_store(STORE.HaScopedTaskStore())
        body = {
            "id": "req-1",
            "jsonrpc": "2.0",
            "method": "tasks/list",
            "params": {},
        }
        result = _call_tasks_list(store, body, user_id="user-a")
        assert result["result"]["totalSize"] == 2
        task_ids = {t["id"] for t in result["result"]["tasks"]}
        assert task_ids == {"t-1", "t-2"}

    @pytest.mark.asyncio
    async def test_other_user_sees_own_tasks(self) -> None:
        store = await _populate_store(STORE.HaScopedTaskStore())
        body = {
            "id": "req-2",
            "jsonrpc": "2.0",
            "method": "tasks/list",
            "params": {},
        }
        result = _call_tasks_list(store, body, user_id="user-b")
        assert result["result"]["totalSize"] == 1
        assert result["result"]["tasks"][0]["id"] == "t-3"

    @pytest.mark.asyncio
    async def test_status_filter(self) -> None:
        store = await _populate_store(STORE.HaScopedTaskStore())
        body = {
            "id": "req-3",
            "jsonrpc": "2.0",
            "method": "tasks/list",
            "params": {"status": "completed"},
        }
        result = _call_tasks_list(store, body, user_id="user-a")
        assert result["result"]["totalSize"] == 1
        assert result["result"]["tasks"][0]["id"] == "t-1"

    @pytest.mark.asyncio
    async def test_context_id_filter(self) -> None:
        store = await _populate_store(STORE.HaScopedTaskStore())
        body = {
            "id": "req-4",
            "jsonrpc": "2.0",
            "method": "tasks/list",
            "params": {"contextId": "c-1"},
        }
        result = _call_tasks_list(store, body, user_id="user-a")
        assert result["result"]["totalSize"] == 2


class TestTasksListPagination:
    """Test page_size and page_token behavior."""

    @pytest.mark.asyncio
    async def test_pagination(self) -> None:
        store = await _populate_store(STORE.HaScopedTaskStore())
        body = {
            "id": "req-5",
            "jsonrpc": "2.0",
            "method": "tasks/list",
            "params": {"pageSize": 1, "pageToken": "0"},
        }
        result = _call_tasks_list(store, body, user_id="user-a")
        assert len(result["result"]["tasks"]) == 1
        assert result["result"]["totalSize"] == 2
        assert result["result"]["nextPageToken"] == "1"

    @pytest.mark.asyncio
    async def test_second_page(self) -> None:
        store = await _populate_store(STORE.HaScopedTaskStore())
        body = {
            "id": "req-6",
            "jsonrpc": "2.0",
            "method": "tasks/list",
            "params": {"pageSize": 1, "pageToken": "1"},
        }
        result = _call_tasks_list(store, body, user_id="user-a")
        assert len(result["result"]["tasks"]) == 1
        assert result["result"]["nextPageToken"] == ""


class TestTasksListRendering:
    """Test history truncation and artifact exclusion."""

    @pytest.mark.asyncio
    async def test_artifacts_excluded_by_default(self) -> None:
        store = await _populate_store(STORE.HaScopedTaskStore())
        body = {
            "id": "req-7",
            "jsonrpc": "2.0",
            "method": "tasks/list",
            "params": {},
        }
        result = _call_tasks_list(store, body, user_id="user-a")
        for task in result["result"]["tasks"]:
            assert "artifacts" not in task or task.get("artifacts") is None

    @pytest.mark.asyncio
    async def test_artifacts_included_when_requested(self) -> None:
        store = await _populate_store(STORE.HaScopedTaskStore())
        body = {
            "id": "req-8",
            "jsonrpc": "2.0",
            "method": "tasks/list",
            "params": {"includeArtifacts": True},
        }
        result = _call_tasks_list(store, body, user_id="user-a")
        t1 = next(t for t in result["result"]["tasks"] if t["id"] == "t-1")
        assert t1["artifacts"] is not None
        assert len(t1["artifacts"]) == 1

    @pytest.mark.asyncio
    async def test_history_truncation(self) -> None:
        store = await _populate_store(STORE.HaScopedTaskStore())
        body = {
            "id": "req-9",
            "jsonrpc": "2.0",
            "method": "tasks/list",
            "params": {"historyLength": 1},
        }
        result = _call_tasks_list(store, body, user_id="user-a")
        t1 = next(t for t in result["result"]["tasks"] if t["id"] == "t-1")
        assert len(t1["history"]) == 1

    @pytest.mark.asyncio
    async def test_history_zero_length(self) -> None:
        store = await _populate_store(STORE.HaScopedTaskStore())
        body = {
            "id": "req-10",
            "jsonrpc": "2.0",
            "method": "tasks/list",
            "params": {"historyLength": 0},
        }
        result = _call_tasks_list(store, body, user_id="user-a")
        t1 = next(t for t in result["result"]["tasks"] if t["id"] == "t-1")
        assert t1["history"] == []
