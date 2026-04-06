"""Tests for SSE streaming transport in http.py."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("a2a.types")

from a2a.types import (
    InternalError,
    JSONRPCErrorResponse,
    SendStreamingMessageRequest,
    TaskResubscriptionRequest,
    UnsupportedOperationError,
)
from a2a.utils.errors import ServerError

from .conftest import load_http

HTTP = load_http()


def _make_sse_event(event_obj: object) -> MagicMock:
    """Wrap an SDK event in the structure _handle_streaming expects."""
    wrapper = MagicMock()
    wrapper.root.model_dump_json.return_value = json.dumps({"test": "data"})
    return wrapper


class TestHandleStreaming:
    """Test _handle_streaming SSE transport."""

    async def test_sse_headers(self) -> None:
        """SSE response should have correct content-type and cache headers."""
        handler = MagicMock()

        async def _fake_stream(*_a, **_k):
            return
            yield  # make it an async generator

        handler.on_message_send_stream = MagicMock(return_value=_fake_stream())

        request_obj = MagicMock(spec=SendStreamingMessageRequest)
        request_obj.id = "req-1"

        ha_request = MagicMock()
        stream_response = MagicMock()
        stream_response.prepare = AsyncMock()
        stream_response.write = AsyncMock()
        stream_response.write_eof = AsyncMock()

        with patch.object(HTTP, "web") as mock_web:
            mock_web.StreamResponse.return_value = stream_response
            await HTTP._handle_streaming(handler, request_obj, MagicMock(), ha_request)

        # Verify prepare and write_eof were called
        assert stream_response.prepare.await_count == 1
        assert stream_response.write_eof.await_count == 1
        # Verify StreamResponse was created with SSE headers
        call_kwargs = mock_web.StreamResponse.call_args[1]
        assert call_kwargs["headers"]["Content-Type"] == "text/event-stream"
        assert call_kwargs["headers"]["Cache-Control"] == "no-cache"
        assert call_kwargs["headers"]["Connection"] == "keep-alive"

    async def test_events_written_as_sse(self) -> None:
        """Each yielded event should be written as 'data: <json>\\n\\n'."""
        handler = MagicMock()
        events_data = [
            json.dumps({"status": "working"}),
            json.dumps({"status": "completed"}),
        ]

        async def _fake_stream(*_a, **_k):
            for data in events_data:
                wrapper = MagicMock()
                wrapper.root.model_dump_json.return_value = data
                yield wrapper

        handler.on_message_send_stream = MagicMock(return_value=_fake_stream())

        request_obj = MagicMock(spec=SendStreamingMessageRequest)
        request_obj.id = "req-1"

        ha_request = MagicMock()
        stream_response = MagicMock()
        stream_response.prepare = AsyncMock()
        stream_response.write = AsyncMock()
        stream_response.write_eof = AsyncMock()

        with patch.object(HTTP, "web") as mock_web:
            mock_web.StreamResponse.return_value = stream_response
            await HTTP._handle_streaming(handler, request_obj, MagicMock(), ha_request)

        # Two events + write_eof
        assert stream_response.write.await_count == 2
        for i, data in enumerate(events_data):
            written = stream_response.write.await_args_list[i][0][0]
            assert written == f"data: {data}\n\n".encode()

    async def test_mid_stream_error_writes_error_event(self) -> None:
        """Exception during streaming should write error as final SSE event."""
        handler = MagicMock()

        async def _exploding_stream(*_a, **_k):
            wrapper = MagicMock()
            wrapper.root.model_dump_json.return_value = '{"ok": true}'
            yield wrapper
            raise RuntimeError("stream broke")

        handler.on_message_send_stream = MagicMock(return_value=_exploding_stream())

        request_obj = MagicMock(spec=SendStreamingMessageRequest)
        request_obj.id = "req-1"

        ha_request = MagicMock()
        stream_response = MagicMock()
        stream_response.prepare = AsyncMock()
        stream_response.write = AsyncMock()
        stream_response.write_eof = AsyncMock()

        with patch.object(HTTP, "web") as mock_web:
            mock_web.StreamResponse.return_value = stream_response
            await HTTP._handle_streaming(handler, request_obj, MagicMock(), ha_request)

        # Should have: 1 normal event + 1 error event + write_eof
        assert stream_response.write.await_count == 2
        error_written = stream_response.write.await_args_list[1][0][0].decode()
        assert error_written.startswith("data: ")
        error_payload = json.loads(error_written.removeprefix("data: ").strip())
        assert "error" in error_payload
        assert stream_response.write_eof.await_count == 1

    async def test_capability_gated_returns_json_not_sse(self) -> None:
        """When SDK raises ServerError, return JSON error not SSE stream."""
        handler = MagicMock()
        error = UnsupportedOperationError(message="streaming disabled")
        handler.on_message_send_stream = MagicMock(side_effect=ServerError(error=error))

        request_obj = MagicMock(spec=SendStreamingMessageRequest)
        request_obj.id = "req-1"

        result = await HTTP._handle_streaming(
            handler, request_obj, MagicMock(), MagicMock()
        )

        # Should be a plain web.Response (JSON-RPC error), not StreamResponse
        assert hasattr(result, "body")
        body = json.loads(result.body)
        assert "error" in body

    async def test_resubscribe_routes_correctly(self) -> None:
        """TaskResubscriptionRequest should use on_resubscribe_to_task."""
        handler = MagicMock()

        async def _empty_stream(*_a, **_k):
            return
            yield

        handler.on_resubscribe_to_task = MagicMock(return_value=_empty_stream())

        request_obj = MagicMock(spec=TaskResubscriptionRequest)
        request_obj.id = "req-1"

        ha_request = MagicMock()
        stream_response = MagicMock()
        stream_response.prepare = AsyncMock()
        stream_response.write = AsyncMock()
        stream_response.write_eof = AsyncMock()

        with patch.object(HTTP, "web") as mock_web:
            mock_web.StreamResponse.return_value = stream_response
            await HTTP._handle_streaming(handler, request_obj, MagicMock(), ha_request)

        handler.on_resubscribe_to_task.assert_called_once()


class TestHandleUnary:
    """Test _handle_unary dispatch."""

    async def test_server_error_returns_json_rpc_error(self) -> None:
        """ServerError from SDK capability gating returns error response."""
        handler = MagicMock()
        error = UnsupportedOperationError(message="not supported")
        handler.on_message_send = AsyncMock(side_effect=ServerError(error=error))

        request_obj = MagicMock(spec=SendStreamingMessageRequest)
        request_obj.id = "req-1"
        # Force match to SendMessageRequest for dispatch
        from a2a.types import SendMessageRequest

        request_obj = MagicMock(spec=SendMessageRequest)
        request_obj.id = "req-1"

        result = await HTTP._handle_unary(handler, request_obj, MagicMock())

        body = json.loads(result.body)
        assert "error" in body

    async def test_error_response_passthrough(self) -> None:
        """JSONRPCErrorResponse from handler passes through."""
        handler = MagicMock()
        error_resp = JSONRPCErrorResponse(
            id="req-1",
            error=InternalError(message="something failed"),
        )
        handler.on_message_send = AsyncMock(return_value=error_resp)

        from a2a.types import SendMessageRequest

        request_obj = MagicMock(spec=SendMessageRequest)
        request_obj.id = "req-1"

        result = await HTTP._handle_unary(handler, request_obj, MagicMock())

        body = json.loads(result.body)
        assert "error" in body
        assert body["error"]["message"] == "something failed"
