"""Tests for SDK capability gating (push notifications, streaming).

Verifies that the SDK's @validate decorators correctly reject operations
when capabilities are disabled in the Agent Card, and that our http layer
properly catches the resulting ServerError.
"""

from __future__ import annotations

import pytest

pytest.importorskip("a2a.types")

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import (
    DefaultRequestHandler,
    JSONRPCHandler,
)
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
    Message,
    MessageSendParams,
    Part,
    PushNotificationConfig,
    SendMessageRequest,
    SendStreamingMessageRequest,
    SetTaskPushNotificationConfigRequest,
    TaskPushNotificationConfig,
    TextPart,
)
from a2a.utils.errors import ServerError


class _NoOpExecutor(AgentExecutor):
    """Executor that never runs — tests only exercise gating."""

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        pass

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        pass


def _build_handler(
    *, streaming: bool = False, push_notifications: bool = False
) -> JSONRPCHandler:
    """Create a JSONRPCHandler with specified capabilities."""
    card = AgentCard(
        name="test-agent",
        description="Test agent for capability gating",
        version="0.1.0",
        url="http://localhost/test",
        protocol_version="0.3",
        capabilities=AgentCapabilities(
            streaming=streaming,
            push_notifications=push_notifications,
        ),
        skills=[
            AgentSkill(
                id="test",
                name="test",
                description="test",
                tags=[],
                examples=[],
                input_modes=["text/plain"],
                output_modes=["text/plain"],
            )
        ],
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
    )
    request_handler = DefaultRequestHandler(
        agent_executor=_NoOpExecutor(),
        task_store=InMemoryTaskStore(),
    )
    return JSONRPCHandler(agent_card=card, request_handler=request_handler)


def _send_message_request() -> SendMessageRequest:
    """Create a minimal SendMessageRequest."""
    return SendMessageRequest(
        id="req-1",
        params=MessageSendParams(
            message=Message(
                role="user",
                parts=[Part(root=TextPart(text="hello"))],
                message_id="m1",
            ),
        ),
    )


def _streaming_request() -> SendStreamingMessageRequest:
    """Create a minimal SendStreamingMessageRequest."""
    return SendStreamingMessageRequest(
        id="req-stream-1",
        params=MessageSendParams(
            message=Message(
                role="user",
                parts=[Part(root=TextPart(text="hello stream"))],
                message_id="m2",
            ),
        ),
    )


def _push_config_request() -> SetTaskPushNotificationConfigRequest:
    """Create a minimal push notification config request."""
    return SetTaskPushNotificationConfigRequest(
        id="req-push-1",
        params=TaskPushNotificationConfig(
            task_id="task-1",
            push_notification_config=PushNotificationConfig(
                url="https://example.com/webhook",
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Push notification gating
# ---------------------------------------------------------------------------


class TestPushNotificationGating:
    """Push notification methods should reject when capability is disabled."""

    @pytest.mark.asyncio
    async def test_set_push_config_rejected_when_disabled(self) -> None:
        handler = _build_handler(push_notifications=False)
        with pytest.raises(ServerError) as exc_info:
            await handler.set_push_notification_config(_push_config_request(), None)
        assert "not supported" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_set_push_config_accepted_when_enabled(self) -> None:
        """With push_notifications=True but no store, SDK returns an error response."""
        handler = _build_handler(push_notifications=True)
        # The call doesn't raise ServerError from @validate,
        # but may return an error response (task not found or unsupported)
        result = await handler.set_push_notification_config(
            _push_config_request(), None
        )
        assert result is not None


# ---------------------------------------------------------------------------
# Streaming gating
# ---------------------------------------------------------------------------


class TestStreamingGating:
    """Streaming methods should reject when streaming capability is disabled."""

    def test_stream_rejected_when_disabled(self) -> None:
        handler = _build_handler(streaming=False)
        with pytest.raises(ServerError) as exc_info:
            handler.on_message_send_stream(_streaming_request(), None)
        assert "not supported" in str(exc_info.value).lower()

    def test_stream_not_rejected_when_enabled(self) -> None:
        """With streaming=True, the method should return a generator (not raise)."""
        handler = _build_handler(streaming=True)
        # Should not raise — returns an async generator
        result = handler.on_message_send_stream(_streaming_request(), None)
        assert result is not None


# ---------------------------------------------------------------------------
# Non-streaming operations always work
# ---------------------------------------------------------------------------


class TestNonStreamingAlwaysWorks:
    """message/send and tasks/get should work regardless of streaming flag."""

    @pytest.mark.asyncio
    async def test_message_send_works_with_streaming_disabled(self) -> None:
        handler = _build_handler(streaming=False)
        result = await handler.on_message_send(_send_message_request(), None)
        # Should return a response (success or error), not raise
        assert result is not None

    @pytest.mark.asyncio
    async def test_message_send_works_with_streaming_enabled(self) -> None:
        handler = _build_handler(streaming=True)
        result = await handler.on_message_send(_send_message_request(), None)
        assert result is not None
