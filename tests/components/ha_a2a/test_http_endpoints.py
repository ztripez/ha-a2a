"""Integration tests for HTTP endpoint views."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("a2a.types")

from .conftest import load_http, load_models

HTTP = load_http()
MODELS = load_models()


def _make_json_rpc_body(
    method: str,
    *,
    request_id: str | int = "test-1",
    params: dict | None = None,
) -> dict:
    """Build a minimal JSON-RPC 2.0 request body."""
    body: dict = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
    }
    if params is not None:
        body["params"] = params
    return body


class TestJsonRpcErrorResponse:
    """Test _json_rpc_error_response helper."""

    def test_produces_valid_json_rpc_error(self) -> None:
        from a2a.types import InternalError

        resp = HTTP._json_rpc_error_response(
            request_id="req-1",
            error=InternalError(message="boom"),
        )
        body = json.loads(resp.body)
        assert body["jsonrpc"] == "2.0"
        assert body["id"] == "req-1"
        assert body["error"]["code"] == -32603
        assert body["error"]["message"] == "boom"

    def test_null_request_id(self) -> None:
        from a2a.types import JSONParseError

        resp = HTTP._json_rpc_error_response(
            request_id=None,
            error=JSONParseError(),
        )
        body = json.loads(resp.body)
        # id=None is excluded by exclude_none serialization
        assert body.get("id") is None
        assert body["error"]["code"] == -32700


class TestValidateA2AVersion:
    """Test _validate_a2a_version (beyond existing tests in test_http.py)."""

    def test_whitespace_stripped(self) -> None:
        request = MagicMock()
        request.headers = {"A2A-Version": "  0.3  "}
        request.query = {}
        assert HTTP._validate_a2a_version(request) is True


class TestEvictStaleRuntimes:
    """Test _evict_stale_runtimes helper."""

    def test_evicts_removed_assistants(self) -> None:
        runtimes = {"active-1": MagicMock(), "removed-1": MagicMock()}
        agents = [MagicMock(assistant_id="active-1")]
        HTTP._evict_stale_runtimes(runtimes, agents)
        assert "active-1" in runtimes
        assert "removed-1" not in runtimes

    def test_noop_when_all_active(self) -> None:
        runtimes = {"a": MagicMock(), "b": MagicMock()}
        agents = [
            MagicMock(assistant_id="a"),
            MagicMock(assistant_id="b"),
        ]
        HTTP._evict_stale_runtimes(runtimes, agents)
        assert len(runtimes) == 2

    def test_clears_all_when_no_agents(self) -> None:
        runtimes = {"a": MagicMock(), "b": MagicMock()}
        HTTP._evict_stale_runtimes(runtimes, [])
        assert len(runtimes) == 0


class TestDispatchUnary:
    """Test _dispatch_unary match/case routing."""

    async def test_send_message_routes(self) -> None:
        from a2a.types import SendMessageRequest

        handler = MagicMock()
        handler.on_message_send = AsyncMock(return_value=MagicMock())
        req = MagicMock(spec=SendMessageRequest)
        await HTTP._dispatch_unary(handler, req, MagicMock())
        handler.on_message_send.assert_awaited_once()

    async def test_get_task_routes(self) -> None:
        from a2a.types import GetTaskRequest

        handler = MagicMock()
        handler.on_get_task = AsyncMock(return_value=MagicMock())
        req = MagicMock(spec=GetTaskRequest)
        await HTTP._dispatch_unary(handler, req, MagicMock())
        handler.on_get_task.assert_awaited_once()

    async def test_cancel_task_routes(self) -> None:
        from a2a.types import CancelTaskRequest

        handler = MagicMock()
        handler.on_cancel_task = AsyncMock(return_value=MagicMock())
        req = MagicMock(spec=CancelTaskRequest)
        await HTTP._dispatch_unary(handler, req, MagicMock())
        handler.on_cancel_task.assert_awaited_once()

    async def test_set_push_config_routes(self) -> None:
        from a2a.types import SetTaskPushNotificationConfigRequest

        handler = MagicMock()
        handler.set_push_notification_config = AsyncMock(return_value=MagicMock())
        req = MagicMock(spec=SetTaskPushNotificationConfigRequest)
        await HTTP._dispatch_unary(handler, req, MagicMock())
        handler.set_push_notification_config.assert_awaited_once()

    async def test_get_push_config_routes(self) -> None:
        from a2a.types import GetTaskPushNotificationConfigRequest

        handler = MagicMock()
        handler.get_push_notification_config = AsyncMock(return_value=MagicMock())
        req = MagicMock(spec=GetTaskPushNotificationConfigRequest)
        await HTTP._dispatch_unary(handler, req, MagicMock())
        handler.get_push_notification_config.assert_awaited_once()

    async def test_get_extended_card_routes(self) -> None:
        from a2a.types import GetAuthenticatedExtendedCardRequest

        handler = MagicMock()
        handler.get_authenticated_extended_card = AsyncMock(return_value=MagicMock())
        req = MagicMock(spec=GetAuthenticatedExtendedCardRequest)
        await HTTP._dispatch_unary(handler, req, MagicMock())
        handler.get_authenticated_extended_card.assert_awaited_once()

    async def test_unknown_type_returns_error(self) -> None:
        from a2a.types import JSONRPCErrorResponse

        handler = MagicMock()
        req = MagicMock()
        req.id = "req-1"
        # Not a known request type
        type(req).__name__ = "UnknownRequest"

        result = await HTTP._dispatch_unary(handler, req, MagicMock())
        assert isinstance(result, JSONRPCErrorResponse)
