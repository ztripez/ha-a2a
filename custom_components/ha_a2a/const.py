"""Constants for the ha_a2a integration."""

from __future__ import annotations

DOMAIN = "ha_a2a"

LIST_AGENT_CARDS_PATH = "/api/ha_a2a/agent-cards"
AGENT_CARD_PATH_TEMPLATE = (
    "/api/ha_a2a/agents/{assistant_id}/.well-known/agent-card.json"
)
AGENT_INTERFACE_PATH_TEMPLATE = "/api/ha_a2a/agents/{assistant_id}"
AGENT_RPC_PATH = "/api/ha_a2a/agents/{assistant_id}"

SUPPORTED_A2A_VERSION = "0.3"
AGENT_CARD_VERSION = "0.1.0"

DATA_REGISTRY = "registry"
DATA_STORE = "store"
