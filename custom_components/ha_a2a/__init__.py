"""Home Assistant integration setup for ha_a2a."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .assistant_registry import AssistantRegistry
from .const import DATA_REGISTRY, DATA_STORE, DOMAIN
from .http import A2AAgentCardView, A2AAgentCardsView, A2AAgentRpcView
from .sdk_runtime import AssistantRuntime


@dataclass(slots=True)
class HaA2ARuntimeData:
    """Runtime data attached to each config entry."""

    registry: AssistantRegistry
    runtimes: dict[str, AssistantRuntime]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the ha_a2a domain."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    domain_data[DATA_REGISTRY] = AssistantRegistry(hass)
    domain_data[DATA_STORE] = {}

    hass.http.register_view(A2AAgentCardsView())
    hass.http.register_view(A2AAgentCardView())
    hass.http.register_view(A2AAgentRpcView())
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up ha_a2a from a config entry."""
    domain_data = hass.data[DOMAIN]
    entry.runtime_data = HaA2ARuntimeData(
        registry=domain_data[DATA_REGISTRY],
        runtimes=domain_data[DATA_STORE],
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return True
