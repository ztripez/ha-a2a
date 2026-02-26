"""Unit tests for A2A card model helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import pytest


def _load_models_module():
    """Load models.py without importing Home Assistant runtime modules."""
    pytest.importorskip("a2a.types")

    project_root = Path(__file__).resolve().parents[3]
    package_root = project_root / "custom_components" / "ha_a2a"

    custom_components_pkg = types.ModuleType("custom_components")
    custom_components_pkg.__path__ = [str(project_root / "custom_components")]
    sys.modules.setdefault("custom_components", custom_components_pkg)

    ha_a2a_pkg = types.ModuleType("custom_components.ha_a2a")
    ha_a2a_pkg.__path__ = [str(package_root)]
    sys.modules.setdefault("custom_components.ha_a2a", ha_a2a_pkg)

    for module_name in (
        "custom_components.ha_a2a.const",
        "custom_components.ha_a2a.models",
    ):
        if module_name in sys.modules:
            del sys.modules[module_name]

    const_spec = importlib.util.spec_from_file_location(
        "custom_components.ha_a2a.const", package_root / "const.py"
    )
    assert const_spec and const_spec.loader
    const_module = importlib.util.module_from_spec(const_spec)
    sys.modules["custom_components.ha_a2a.const"] = const_module
    const_spec.loader.exec_module(const_module)

    models_spec = importlib.util.spec_from_file_location(
        "custom_components.ha_a2a.models", package_root / "models.py"
    )
    assert models_spec and models_spec.loader
    models_module = importlib.util.module_from_spec(models_spec)
    sys.modules["custom_components.ha_a2a.models"] = models_module
    models_spec.loader.exec_module(models_module)

    return models_module


MODELS = _load_models_module()


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
