"""Unit tests for A2A card model helpers."""

from __future__ import annotations

import pytest

pytest.importorskip("a2a.types")

from .conftest import load_models

MODELS = load_models()


def test_build_agent_card_path_escapes_assistant_id() -> None:
    """Assistant IDs should be URL escaped in card paths."""
    path = MODELS.build_agent_card_path("conversation.home assistant/1")
    assert path.endswith(
        "/conversation.home%20assistant%2F1/.well-known/agent-card.json"
    )


def test_build_agent_card_contains_expected_fields() -> None:
    """Card payload should include required discovery fields."""
    agent = MODELS.A2AAssistantAgent(
        assistant_id="conversation.home_assistant",
        name="Home Assistant",
        supports_streaming=False,
    )

    card = MODELS.dump_agent_card(
        MODELS.build_agent_card(agent, base_url="https://ha.local")
    )

    assert card["name"] == "Home Assistant"
    assert card["version"] == "0.1.0"
    assert card["url"].startswith("https://ha.local/api/ha_a2a/agents/")
    assert card["preferredTransport"] == "JSONRPC"
    assert card["additionalInterfaces"][0]["transport"] == "JSONRPC"
    assert card["capabilities"]["streaming"] is False
    assert card["capabilities"]["pushNotifications"] is False
    assert card["protocolVersion"] == "0.3"
