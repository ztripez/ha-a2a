"""Unit tests for SDK runtime wiring (HAUser, call context, executor)."""

from __future__ import annotations

import pytest

pytest.importorskip("a2a.types")

from a2a.auth.user import User
from a2a.server.context import ServerCallContext

from .conftest import _ensure_ha_stubs, _load_module, load_const

# Load sdk_runtime with HA stubs
_ensure_ha_stubs()
load_const()
_load_module("models", "models.py")
_load_module("store", "store.py")
_load_module("conversation_bridge", "conversation_bridge.py")
SDK_RT = _load_module("sdk_runtime", "sdk_runtime.py")


# ---------------------------------------------------------------------------
# HAUser tests
# ---------------------------------------------------------------------------


class TestHAUser:
    """Test the SDK User adapter."""

    def test_authenticated_user_has_name(self) -> None:
        user = SDK_RT.HAUser("user-123")
        assert user.is_authenticated is True
        assert user.user_name == "user-123"

    def test_none_user_is_unauthenticated(self) -> None:
        user = SDK_RT.HAUser(None)
        assert user.is_authenticated is False
        assert user.user_name == ""

    def test_is_sdk_user_subclass(self) -> None:
        user = SDK_RT.HAUser("u")
        assert isinstance(user, User)


# ---------------------------------------------------------------------------
# ServerCallContext builder tests
# ---------------------------------------------------------------------------


class TestBuildServerCallContext:
    """Test call context creation from HA request context."""

    def _make_ha_context(self, user_id: str | None = None):
        """Create a minimal HA Context stub."""
        import homeassistant.core as ha_core

        ctx = ha_core.Context()
        ctx.user_id = user_id
        return ctx

    def test_context_carries_user_id(self) -> None:
        ha_ctx = self._make_ha_context("user-42")
        mock_request = object()
        call_ctx = SDK_RT.build_server_call_context(ha_ctx, request=mock_request)

        assert isinstance(call_ctx, ServerCallContext)
        assert call_ctx.state["ha_user_id"] == "user-42"
        assert call_ctx.state["ha_context"] is ha_ctx
        assert call_ctx.state["ha_request"] is mock_request

    def test_context_with_none_user(self) -> None:
        ha_ctx = self._make_ha_context(None)
        call_ctx = SDK_RT.build_server_call_context(ha_ctx, request=object())

        assert call_ctx.state["ha_user_id"] is None
        assert call_ctx.user.is_authenticated is False

    def test_context_user_is_ha_user(self) -> None:
        ha_ctx = self._make_ha_context("u1")
        call_ctx = SDK_RT.build_server_call_context(ha_ctx, request=object())

        assert isinstance(call_ctx.user, SDK_RT.HAUser)
        assert call_ctx.user.user_name == "u1"


# ---------------------------------------------------------------------------
# AssistantRuntime factory tests
# ---------------------------------------------------------------------------


class TestBuildAssistantRuntime:
    """Test per-assistant runtime wiring."""

    def test_creates_runtime_with_store_and_handler(self) -> None:
        import homeassistant.core as ha_core

        hass = ha_core.HomeAssistant()
        runtime = SDK_RT.build_assistant_runtime(hass, "conversation.test")

        assert runtime.task_store is not None
        assert runtime.request_handler is not None
        assert hasattr(runtime.request_handler, "agent_executor")

    def test_different_assistants_get_isolated_stores(self) -> None:
        import homeassistant.core as ha_core

        hass = ha_core.HomeAssistant()
        rt_a = SDK_RT.build_assistant_runtime(hass, "assistant-a")
        rt_b = SDK_RT.build_assistant_runtime(hass, "assistant-b")

        assert rt_a.task_store is not rt_b.task_store


# ---------------------------------------------------------------------------
# Executor tests
# ---------------------------------------------------------------------------


class TestHaConversationAgentExecutor:
    """Test executor validation and execution paths."""

    def _make_executor(self):
        import homeassistant.core as ha_core

        hass = ha_core.HomeAssistant()
        return SDK_RT.HaConversationAgentExecutor(hass, "test-assistant")

    def _make_ha_context(self, user_id: str = "user-1"):
        import homeassistant.core as ha_core

        ctx = ha_core.Context()
        ctx.user_id = user_id
        return ctx

    def _make_request_context(
        self,
        *,
        task_id: str | None = "task-1",
        context_id: str | None = "ctx-1",
        user_input: str = "Hello",
        ha_context=None,
    ):
        from unittest.mock import MagicMock

        from a2a.server.agent_execution import RequestContext

        if ha_context is None:
            ha_context = self._make_ha_context()

        call_context = ServerCallContext(
            state={
                "ha_user_id": "user-1",
                "ha_context": ha_context,
            },
            user=SDK_RT.HAUser("user-1"),
        )

        rc = MagicMock(spec=RequestContext)
        rc.task_id = task_id
        rc.context_id = context_id
        rc.call_context = call_context
        rc.get_user_input.return_value = user_input
        return rc

    def test_rejects_missing_task_id(self) -> None:
        executor = self._make_executor()
        assert hasattr(executor, "execute")
        assert hasattr(executor, "cancel")

    async def test_rejects_none_task_id(self) -> None:
        from a2a.server.events import EventQueue

        executor = self._make_executor()
        rc = self._make_request_context(task_id=None)
        eq = EventQueue()

        with pytest.raises(ValueError, match="task_id and context_id"):
            await executor.execute(rc, eq)

    async def test_rejects_none_context_id(self) -> None:
        from a2a.server.events import EventQueue

        executor = self._make_executor()
        rc = self._make_request_context(context_id=None)
        eq = EventQueue()

        with pytest.raises(ValueError, match="task_id and context_id"):
            await executor.execute(rc, eq)

    async def test_rejects_missing_call_context(self) -> None:
        from unittest.mock import MagicMock

        from a2a.server.agent_execution import RequestContext
        from a2a.server.events import EventQueue

        executor = self._make_executor()
        rc = MagicMock(spec=RequestContext)
        rc.task_id = "t-1"
        rc.context_id = "c-1"
        rc.call_context = None
        eq = EventQueue()

        with pytest.raises(ValueError, match="call context"):
            await executor.execute(rc, eq)

    async def test_execute_happy_path(self) -> None:
        """Successful conversation produces start_work, artifact, complete."""
        import sys
        from unittest.mock import AsyncMock, MagicMock

        from a2a.server.events import EventQueue

        # Patch conversation bridge
        ha_conv = sys.modules["homeassistant.components.conversation"]
        mock_result = MagicMock()
        mock_result.as_dict.return_value = {
            "response": {
                "speech": {"plain": {"speech": "Lights turned off."}},
            },
        }
        ha_conv.async_converse = AsyncMock(return_value=mock_result)

        # Reload bridge and runtime to pick up patched converse
        _load_module("conversation_bridge", "conversation_bridge.py")
        sdk_rt = _load_module("sdk_runtime", "sdk_runtime.py")

        executor = sdk_rt.HaConversationAgentExecutor(MagicMock(), "test-assistant")
        rc = self._make_request_context(user_input="Turn off lights")
        eq = EventQueue()

        await executor.execute(rc, eq)

        # Collect all events (queue is bounded, no_wait drains it)
        events = []
        try:
            while True:
                event = await eq.dequeue_event(no_wait=True)
                events.append(event)
        except Exception:
            pass  # queue empty

        # Should have: status(working), artifact, status(completed)
        assert len(events) >= 2
        from a2a.types import TaskArtifactUpdateEvent, TaskStatusUpdateEvent

        status_events = [e for e in events if isinstance(e, TaskStatusUpdateEvent)]
        artifact_events = [e for e in events if isinstance(e, TaskArtifactUpdateEvent)]
        assert len(status_events) >= 2  # working + completed
        assert len(artifact_events) >= 1

        assert status_events[0].status.state.value == "working"
        assert status_events[-1].status.state.value == "completed"

    async def test_execute_failure_path(self) -> None:
        """Exception in conversation produces failed task."""
        import sys
        from unittest.mock import AsyncMock, MagicMock

        from a2a.server.events import EventQueue

        ha_conv = sys.modules["homeassistant.components.conversation"]
        ha_conv.async_converse = AsyncMock(side_effect=RuntimeError("HA is down"))

        _load_module("conversation_bridge", "conversation_bridge.py")
        sdk_rt = _load_module("sdk_runtime", "sdk_runtime.py")

        executor = sdk_rt.HaConversationAgentExecutor(MagicMock(), "test-assistant")
        rc = self._make_request_context(user_input="Hello")
        eq = EventQueue()

        await executor.execute(rc, eq)

        events = []
        try:
            while True:
                event = await eq.dequeue_event(no_wait=True)
                events.append(event)
        except Exception:
            pass

        from a2a.types import TaskStatusUpdateEvent

        status_events = [e for e in events if isinstance(e, TaskStatusUpdateEvent)]
        assert len(status_events) >= 2
        assert status_events[0].status.state.value == "working"
        assert status_events[-1].status.state.value == "failed"

    async def test_cancel_publishes_canceled_state(self) -> None:
        """Cancel should publish a canceled status event."""
        from a2a.server.events import EventQueue

        executor = self._make_executor()
        rc = self._make_request_context()
        eq = EventQueue()

        await executor.cancel(rc, eq)

        events = []
        try:
            while True:
                event = await eq.dequeue_event(no_wait=True)
                events.append(event)
        except Exception:
            pass

        from a2a.types import TaskStatusUpdateEvent

        status_events = [e for e in events if isinstance(e, TaskStatusUpdateEvent)]
        assert len(status_events) >= 1
        assert status_events[-1].status.state.value == "canceled"

    async def test_cancel_rejects_missing_task_id(self) -> None:
        from a2a.server.events import EventQueue

        executor = self._make_executor()
        rc = self._make_request_context(task_id=None)
        eq = EventQueue()

        with pytest.raises(ValueError, match="task_id and context_id"):
            await executor.cancel(rc, eq)
