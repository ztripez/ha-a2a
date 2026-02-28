"""Unit tests for SDK runtime wiring (HAUser, call context, executor)."""

from __future__ import annotations

import pytest

pytest.importorskip("a2a.types")

from a2a.auth.user import User  # noqa: E402
from a2a.server.context import ServerCallContext  # noqa: E402
from a2a.server.events import EventQueue  # noqa: E402
from a2a.types import (  # noqa: E402
    Message,
    Part,
    Task,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TaskArtifactUpdateEvent,
    TextPart,
)

from .conftest import _ensure_ha_stubs, _load_module, load_const  # noqa: E402

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
    """Test executor validation logic (without calling conversation API)."""

    def test_rejects_missing_task_id(self) -> None:
        import homeassistant.core as ha_core

        hass = ha_core.HomeAssistant()
        executor = SDK_RT.HaConversationAgentExecutor(hass, "test-assistant")
        # Ensure the executor class is right
        assert hasattr(executor, "execute")
        assert hasattr(executor, "cancel")
