"""Assistant-to-agent registry for per-assistant A2A identities."""

from __future__ import annotations

from homeassistant.components import conversation
from homeassistant.components.conversation.agent_manager import get_agent_manager
from homeassistant.components.conversation.const import (
    DATA_COMPONENT as CONVERSATION_DATA_COMPONENT,
)
from homeassistant.components.conversation.const import (
    HOME_ASSISTANT_AGENT,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .models import A2AAssistantAgent


class AssistantRegistry:
    """Resolve Home Assistant assistants as stable A2A agents."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the assistant registry."""
        self._hass = hass

    async def async_list_agents(self) -> list[A2AAssistantAgent]:
        """Return all available assistants mapped to A2A identities."""
        if conversation.DOMAIN not in self._hass.config.components:
            raise HomeAssistantError("conversation integration is not loaded")

        result: dict[str, A2AAssistantAgent] = {}

        default_info = conversation.async_get_agent_info(
            self._hass, HOME_ASSISTANT_AGENT
        )
        if default_info is not None:
            result[default_info.id] = A2AAssistantAgent(
                assistant_id=default_info.id,
                name=default_info.name,
                supports_streaming=default_info.supports_streaming,
            )

        manager = get_agent_manager(self._hass)
        for agent_info in manager.async_get_agent_info():
            result[agent_info.id] = A2AAssistantAgent(
                assistant_id=agent_info.id,
                name=agent_info.name,
                supports_streaming=agent_info.supports_streaming,
            )

        component = self._hass.data.get(CONVERSATION_DATA_COMPONENT)
        if component is not None:
            for entity in component.entities:
                entity_name = entity.name
                if not isinstance(entity_name, str):
                    entity_name = entity.entity_id

                result[entity.entity_id] = A2AAssistantAgent(
                    assistant_id=entity.entity_id,
                    name=entity_name,
                    supports_streaming=bool(
                        getattr(entity, "supports_streaming", False)
                    ),
                )

        return sorted(result.values(), key=lambda agent: agent.assistant_id)

    async def async_get_agent(self, assistant_id: str) -> A2AAssistantAgent | None:
        """Get one assistant mapping by ID."""
        agents = await self.async_list_agents()
        for agent in agents:
            if agent.assistant_id == assistant_id:
                return agent

        return None
