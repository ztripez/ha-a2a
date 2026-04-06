"""Tests for HaA2AConfigFlow."""

from __future__ import annotations

from .conftest import _ensure_ha_stubs, _load_module

_ensure_ha_stubs()

import sys  # noqa: E402

# Extend config_entries stub with ConfigFlow base class and decorators
ha_config_entries = sys.modules["homeassistant.config_entries"]
if not hasattr(ha_config_entries, "ConfigFlow"):

    class _FlowResult(dict):
        pass

    class _ConfigFlowMeta(type):
        def __init_subclass__(cls, **kwargs):
            pass

        def __new__(mcs, name, bases, namespace, domain=None, **kwargs):
            cls = super().__new__(mcs, name, bases, namespace)
            if domain is not None:
                cls.DOMAIN = domain
            return cls

    class ConfigFlow(metaclass=_ConfigFlowMeta):
        """Minimal ConfigFlow stub for testing."""

        _unique_id: str | None = None
        _abort_unique: bool = False

        async def async_set_unique_id(self, uid: str) -> None:
            self._unique_id = uid

        def _abort_if_unique_id_configured(self) -> None:
            if self._abort_unique:
                raise AbortFlow("already_configured")

        def async_create_entry(self, *, title: str, data: dict) -> dict:
            return {
                "type": "create_entry",
                "title": title,
                "data": data,
            }

        def async_show_form(self, *, step_id: str, data_schema) -> dict:
            return {
                "type": "form",
                "step_id": step_id,
            }

    class AbortFlow(Exception):
        pass

    ha_config_entries.ConfigFlow = ConfigFlow
    ha_config_entries.AbortFlow = AbortFlow


config_flow_mod = _load_module("config_flow", "config_flow.py")


class TestHaA2AConfigFlow:
    """Test config flow for ha_a2a."""

    async def test_step_user_shows_form_initially(self) -> None:
        flow = config_flow_mod.HaA2AConfigFlow()
        result = await flow.async_step_user(user_input=None)
        assert result["type"] == "form"
        assert result["step_id"] == "user"

    async def test_step_user_creates_entry(self) -> None:
        flow = config_flow_mod.HaA2AConfigFlow()
        result = await flow.async_step_user(user_input={})
        assert result["type"] == "create_entry"
        assert result["title"] == "Home Assistant A2A"
        assert result["data"] == {}

    async def test_version_is_set(self) -> None:
        assert config_flow_mod.HaA2AConfigFlow.VERSION == 1

    async def test_unique_id_set_on_create(self) -> None:
        flow = config_flow_mod.HaA2AConfigFlow()
        await flow.async_step_user(user_input={})
        assert flow._unique_id == "ha_a2a"
