"""Unit tests for in-memory task store behavior."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
from types import SimpleNamespace

import pytest


def _load_store_module():
    """Load store.py with package-relative imports resolved."""
    pytest.importorskip("a2a.types")

    project_root = Path(__file__).resolve().parents[3]
    package_root = project_root / "custom_components" / "ha_a2a"

    custom_components_pkg = types.ModuleType("custom_components")
    custom_components_pkg.__path__ = [str(project_root / "custom_components")]
    sys.modules.setdefault("custom_components", custom_components_pkg)

    ha_a2a_pkg = types.ModuleType("custom_components.ha_a2a")
    ha_a2a_pkg.__path__ = [str(package_root)]
    sys.modules.setdefault("custom_components.ha_a2a", ha_a2a_pkg)

    for module_name in (
        "custom_components.ha_a2a.const",
        "custom_components.ha_a2a.store",
    ):
        if module_name in sys.modules:
            del sys.modules[module_name]

    const_spec = importlib.util.spec_from_file_location(
        "custom_components.ha_a2a.const", package_root / "const.py"
    )
    assert const_spec and const_spec.loader
    const_module = importlib.util.module_from_spec(const_spec)
    sys.modules["custom_components.ha_a2a.const"] = const_module
    const_spec.loader.exec_module(const_module)

    store_spec = importlib.util.spec_from_file_location(
        "custom_components.ha_a2a.store", package_root / "store.py"
    )
    assert store_spec and store_spec.loader
    store_module = importlib.util.module_from_spec(store_spec)
    sys.modules["custom_components.ha_a2a.store"] = store_module
    store_spec.loader.exec_module(store_module)
    return store_module


STORE = _load_store_module()

from a2a.server.context import ServerCallContext
from a2a.types import Task, TaskState, TaskStatus


def _context(user_id: str) -> ServerCallContext:
    return ServerCallContext(
        state={"ha_user_id": user_id},
        user=SimpleNamespace(is_authenticated=True, user_name=user_id),
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
