"""Config flow for ha_a2a."""

from __future__ import annotations

from homeassistant import config_entries

from .const import DOMAIN


class HaA2AConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for ha_a2a."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        if user_input is not None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title="Home Assistant A2A", data={})

        return self.async_show_form(step_id="user", data_schema=None)
