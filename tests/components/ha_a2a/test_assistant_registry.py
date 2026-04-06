"""Tests for AssistantRegistry."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from .conftest import _ensure_ha_stubs, _load_module

_ensure_ha_stubs()


def _make_agent_info(
    agent_id: str,
    name: str,
    supports_streaming: bool = False,
) -> MagicMock:
    """Create a mock HA AgentInfo."""
    info = MagicMock()
    info.id = agent_id
    info.name = name
    info.supports_streaming = supports_streaming
    return info


def _make_entity(
    entity_id: str,
    name: str | None = None,
    supports_streaming: bool = False,
) -> MagicMock:
    """Create a mock conversation entity."""
    entity = MagicMock()
    entity.entity_id = entity_id
    entity.name = name if name is not None else entity_id
    entity.supports_streaming = supports_streaming
    return entity


def _make_hass(
    *,
    default_agent: MagicMock | None = None,
    manager_agents: list[MagicMock] | None = None,
    entities: list[MagicMock] | None = None,
    conversation_loaded: bool = True,
) -> MagicMock:
    """Build a mock hass object wired for AssistantRegistry."""
    import sys

    hass = MagicMock()
    hass.config.components = {"conversation"} if conversation_loaded else set()

    # Wire async_get_agent_info
    ha_conv = sys.modules["homeassistant.components.conversation"]
    ha_conv.async_get_agent_info = MagicMock(return_value=default_agent)

    # Wire agent manager
    manager = MagicMock()
    manager.async_get_agent_info.return_value = manager_agents or []
    ha_conv_mgr = sys.modules["homeassistant.components.conversation.agent_manager"]
    ha_conv_mgr.get_agent_manager = MagicMock(return_value=manager)

    # Wire conversation entities
    ha_conv_const = sys.modules["homeassistant.components.conversation.const"]
    if entities is not None:
        component = MagicMock()
        component.entities = entities
        hass.data = {ha_conv_const.DATA_COMPONENT: component}
    else:
        hass.data = {}

    return hass


class TestAsyncListAgents:
    """Test AssistantRegistry.async_list_agents."""

    async def test_returns_default_agent(self) -> None:
        default = _make_agent_info("homeassistant", "Home Assistant")
        hass = _make_hass(default_agent=default)
        registry_mod = _load_module("assistant_registry", "assistant_registry.py")
        registry = registry_mod.AssistantRegistry(hass)

        agents = await registry.async_list_agents()

        assert len(agents) == 1
        assert agents[0].assistant_id == "homeassistant"
        assert agents[0].name == "Home Assistant"

    async def test_returns_manager_agents(self) -> None:
        mgr_agents = [
            _make_agent_info("agent-1", "Agent One", True),
            _make_agent_info("agent-2", "Agent Two", False),
        ]
        hass = _make_hass(manager_agents=mgr_agents)
        registry_mod = _load_module("assistant_registry", "assistant_registry.py")
        registry = registry_mod.AssistantRegistry(hass)

        agents = await registry.async_list_agents()

        ids = [a.assistant_id for a in agents]
        assert "agent-1" in ids
        assert "agent-2" in ids

    async def test_returns_conversation_entities(self) -> None:
        entities = [_make_entity("conversation.gpt", "GPT Assistant")]
        hass = _make_hass(entities=entities)
        registry_mod = _load_module("assistant_registry", "assistant_registry.py")
        registry = registry_mod.AssistantRegistry(hass)

        agents = await registry.async_list_agents()

        ids = [a.assistant_id for a in agents]
        assert "conversation.gpt" in ids

    async def test_deduplication_by_id(self) -> None:
        """Same ID from multiple sources should appear once."""
        default = _make_agent_info("shared-id", "Default Name")
        mgr_agents = [_make_agent_info("shared-id", "Manager Name")]
        hass = _make_hass(default_agent=default, manager_agents=mgr_agents)
        registry_mod = _load_module("assistant_registry", "assistant_registry.py")
        registry = registry_mod.AssistantRegistry(hass)

        agents = await registry.async_list_agents()

        matching = [a for a in agents if a.assistant_id == "shared-id"]
        assert len(matching) == 1

    async def test_sorted_by_assistant_id(self) -> None:
        mgr_agents = [
            _make_agent_info("z-agent", "Zeta"),
            _make_agent_info("a-agent", "Alpha"),
        ]
        hass = _make_hass(manager_agents=mgr_agents)
        registry_mod = _load_module("assistant_registry", "assistant_registry.py")
        registry = registry_mod.AssistantRegistry(hass)

        agents = await registry.async_list_agents()

        ids = [a.assistant_id for a in agents]
        assert ids == sorted(ids)

    async def test_raises_when_conversation_not_loaded(self) -> None:
        hass = _make_hass(conversation_loaded=False)
        registry_mod = _load_module("assistant_registry", "assistant_registry.py")

        import sys

        ha_exceptions = sys.modules["homeassistant.exceptions"]

        registry = registry_mod.AssistantRegistry(hass)
        with pytest.raises(ha_exceptions.HomeAssistantError):
            await registry.async_list_agents()


class TestAsyncGetAgent:
    """Test AssistantRegistry.async_get_agent."""

    async def test_returns_matching_agent(self) -> None:
        default = _make_agent_info("homeassistant", "Home Assistant")
        hass = _make_hass(default_agent=default)
        registry_mod = _load_module("assistant_registry", "assistant_registry.py")
        registry = registry_mod.AssistantRegistry(hass)

        agent = await registry.async_get_agent("homeassistant")

        assert agent is not None
        assert agent.assistant_id == "homeassistant"

    async def test_returns_none_for_unknown(self) -> None:
        hass = _make_hass()
        registry_mod = _load_module("assistant_registry", "assistant_registry.py")
        registry = registry_mod.AssistantRegistry(hass)

        agent = await registry.async_get_agent("nonexistent")

        assert agent is None
