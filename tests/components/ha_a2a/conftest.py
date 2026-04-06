"""Shared test fixtures for ha_a2a component tests.

Loads integration modules without a full Home Assistant runtime by stubbing
homeassistant dependencies and wiring package paths for ``custom_components``.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_ROOT = PROJECT_ROOT / "custom_components" / "ha_a2a"


def _ensure_package_stubs() -> None:
    """Register minimal stubs so integration modules can be imported."""
    # Package paths
    cc_pkg = types.ModuleType("custom_components")
    cc_pkg.__path__ = [str(PROJECT_ROOT / "custom_components")]
    sys.modules.setdefault("custom_components", cc_pkg)

    ha_a2a_pkg = types.ModuleType("custom_components.ha_a2a")
    ha_a2a_pkg.__path__ = [str(PACKAGE_ROOT)]
    sys.modules.setdefault("custom_components.ha_a2a", ha_a2a_pkg)


def _load_module(name: str, filename: str) -> types.ModuleType:
    """Load a single module from the integration package by filename."""
    fqn = f"custom_components.ha_a2a.{name}"
    if fqn in sys.modules:
        del sys.modules[fqn]

    spec = importlib.util.spec_from_file_location(fqn, PACKAGE_ROOT / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[fqn] = module
    spec.loader.exec_module(module)
    return module


def load_const() -> types.ModuleType:
    """Load ``const.py``."""
    _ensure_package_stubs()
    return _load_module("const", "const.py")


def load_models() -> types.ModuleType:
    """Load ``models.py`` (depends on const)."""
    _ensure_package_stubs()
    load_const()
    return _load_module("models", "models.py")


def load_store() -> types.ModuleType:
    """Load ``store.py`` (depends on const)."""
    _ensure_package_stubs()
    load_const()
    return _load_module("store", "store.py")


def _ensure_ha_stubs() -> None:
    """Register minimal homeassistant stubs for modules that import HA."""
    _ensure_package_stubs()

    # Hierarchical HA package stubs
    _HA_STUBS = (
        "homeassistant",
        "homeassistant.core",
        "homeassistant.components",
        "homeassistant.components.http",
        "homeassistant.components.conversation",
        "homeassistant.components.conversation.agent_manager",
        "homeassistant.components.conversation.const",
        "homeassistant.config_entries",
        "homeassistant.helpers",
        "homeassistant.helpers.typing",
        "homeassistant.exceptions",
    )
    for mod_name in _HA_STUBS:
        if mod_name not in sys.modules:
            stub = types.ModuleType(mod_name)
            # Packages need __path__ for sub-imports to resolve
            if mod_name in (
                "homeassistant",
                "homeassistant.components",
                "homeassistant.helpers",
            ):
                stub.__path__ = []
            sys.modules[mod_name] = stub

    # Sentinel classes expected by integration modules
    ha_core = sys.modules["homeassistant.core"]
    if not hasattr(ha_core, "Context"):

        class Context:
            user_id: str | None = None

        ha_core.Context = Context

    if not hasattr(ha_core, "HomeAssistant"):

        class HomeAssistant:
            pass

        ha_core.HomeAssistant = HomeAssistant

    ha_exceptions = sys.modules["homeassistant.exceptions"]
    if not hasattr(ha_exceptions, "HomeAssistantError"):

        class HomeAssistantError(Exception):
            pass

        ha_exceptions.HomeAssistantError = HomeAssistantError

    ha_config_entries = sys.modules["homeassistant.config_entries"]
    if not hasattr(ha_config_entries, "ConfigEntry"):

        class ConfigEntry:
            pass

        ha_config_entries.ConfigEntry = ConfigEntry

    # HomeAssistantView stub needed by http.py
    ha_http_stub = sys.modules["homeassistant.components.http"]
    if not hasattr(ha_http_stub, "HomeAssistantView"):

        class _FakeView:
            pass

        ha_http_stub.HomeAssistantView = _FakeView
        ha_http_stub.KEY_HASS = "hass"

    # conversation stubs
    ha_conv = sys.modules["homeassistant.components.conversation"]
    if not hasattr(ha_conv, "async_converse"):
        ha_conv.async_converse = None
        ha_conv.async_get_agent_info = None
        ha_conv.DOMAIN = "conversation"

    ha_conv_const = sys.modules["homeassistant.components.conversation.const"]
    if not hasattr(ha_conv_const, "HOME_ASSISTANT_AGENT"):
        ha_conv_const.HOME_ASSISTANT_AGENT = "homeassistant"
        ha_conv_const.DATA_COMPONENT = "conversation_data"

    ha_conv_mgr = sys.modules["homeassistant.components.conversation.agent_manager"]
    if not hasattr(ha_conv_mgr, "get_agent_manager"):
        ha_conv_mgr.get_agent_manager = lambda hass: None


def load_http() -> types.ModuleType:
    """Load ``http.py`` (depends on const, models, sdk_runtime, store)."""
    _ensure_ha_stubs()
    load_const()
    load_models()
    load_store()

    # sdk_runtime depends on conversation_bridge which needs HA stubs
    _load_module("conversation_bridge", "conversation_bridge.py")
    _load_module("sdk_runtime", "sdk_runtime.py")
    _load_module("assistant_registry", "assistant_registry.py")

    return _load_module("http", "http.py")
