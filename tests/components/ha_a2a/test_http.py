"""Unit tests for HTTP endpoint helpers and method routing."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytest.importorskip("a2a.types")

from a2a.types import (
    A2ARequest,
    CancelTaskRequest,
    GetTaskRequest,
    SendMessageRequest,
    SendStreamingMessageRequest,
    TaskResubscriptionRequest,
)

from .conftest import load_http, load_models

MODELS = load_models()
HTTP = load_http()


# ---------------------------------------------------------------------------
# Method map tests (derived from SDK A2ARequest union)
# ---------------------------------------------------------------------------

# Derive the same map our http.py uses at module level.
_METHOD_TO_MODEL: dict[str, type] = {
    model.model_fields["method"].default: model
    for model in A2ARequest.model_fields["root"].annotation.__args__
}


class TestMethodMap:
    """Verify the SDK-derived method->model map covers expected methods."""

    def test_contains_message_send(self) -> None:
        assert "message/send" in _METHOD_TO_MODEL
        assert _METHOD_TO_MODEL["message/send"] is SendMessageRequest

    def test_contains_message_stream(self) -> None:
        assert "message/stream" in _METHOD_TO_MODEL
        assert _METHOD_TO_MODEL["message/stream"] is SendStreamingMessageRequest

    def test_contains_tasks_get(self) -> None:
        assert "tasks/get" in _METHOD_TO_MODEL
        assert _METHOD_TO_MODEL["tasks/get"] is GetTaskRequest

    def test_contains_tasks_cancel(self) -> None:
        assert "tasks/cancel" in _METHOD_TO_MODEL
        assert _METHOD_TO_MODEL["tasks/cancel"] is CancelTaskRequest

    def test_contains_tasks_resubscribe(self) -> None:
        assert "tasks/resubscribe" in _METHOD_TO_MODEL
        assert _METHOD_TO_MODEL["tasks/resubscribe"] is TaskResubscriptionRequest

    def test_does_not_contain_tasks_list(self) -> None:
        """tasks/list is our local extension, not in SDK."""
        assert "tasks/list" not in _METHOD_TO_MODEL

    def test_all_standard_methods_covered(self) -> None:
        """Ensure we have at least the 10 standard A2A methods."""
        assert len(_METHOD_TO_MODEL) >= 10


# ---------------------------------------------------------------------------
# Version validation tests
# ---------------------------------------------------------------------------


class TestVersionValidation:
    """Test A2A-Version header validation logic."""

    def _make_request(
        self, *, header: str | None = None, query: str | None = None
    ) -> MagicMock:
        """Create a minimal mock aiohttp request."""
        req = MagicMock()
        headers: dict[str, str] = {}
        query_params: dict[str, str] = {}

        if header is not None:
            headers["A2A-Version"] = header
        if query is not None:
            query_params["A2A-Version"] = query

        req.headers = headers
        req.query = query_params
        return req

    def test_accepts_matching_version(self) -> None:
        req = self._make_request(header="0.3")
        assert HTTP._validate_a2a_version(req) is True

    def test_rejects_wrong_version(self) -> None:
        req = self._make_request(header="0.1")
        assert HTTP._validate_a2a_version(req) is False

    def test_accepts_empty_as_default(self) -> None:
        req = self._make_request()
        assert HTTP._validate_a2a_version(req) is True

    def test_accepts_version_from_query(self) -> None:
        req = self._make_request(query="0.3")
        assert HTTP._validate_a2a_version(req) is True

    def test_rejects_wrong_version_from_query(self) -> None:
        req = self._make_request(query="0.1")
        assert HTTP._validate_a2a_version(req) is False

    def test_header_takes_precedence_over_query(self) -> None:
        req = self._make_request(header="0.3", query="0.1")
        assert HTTP._validate_a2a_version(req) is True


# ---------------------------------------------------------------------------
# tasks/list extension model tests
# ---------------------------------------------------------------------------


class TestTasksListModels:
    """Test the local tasks/list extension request/response models."""

    def test_list_tasks_request_validates(self) -> None:
        body = {
            "id": "req-1",
            "jsonrpc": "2.0",
            "method": "tasks/list",
            "params": {"page_size": 10, "page_token": "0"},
        }
        req = MODELS.ListTasksRequest.model_validate(body)
        assert req.id == "req-1"
        assert req.params.page_size == 10

    def test_list_tasks_request_defaults(self) -> None:
        body = {
            "id": "req-2",
            "jsonrpc": "2.0",
            "method": "tasks/list",
            "params": {},
        }
        req = MODELS.ListTasksRequest.model_validate(body)
        assert req.params.page_size == 50
        assert req.params.page_token == "0"
        assert req.params.include_artifacts is False
        assert req.params.history_length is None

    def test_parse_task_state_handles_enum_prefix(self) -> None:
        from a2a.types import TaskState

        result = MODELS.parse_task_state("TASK_STATE_COMPLETED")
        assert result == TaskState.completed

    def test_parse_task_state_handles_bare_value(self) -> None:
        from a2a.types import TaskState

        result = MODELS.parse_task_state("working")
        assert result == TaskState.working

    def test_parse_task_state_returns_none_for_none(self) -> None:
        assert MODELS.parse_task_state(None) is None
