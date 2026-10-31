"""Simple UI configuration flow; no Xiaomi credentials requested."""
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from .const import DOMAIN, CONF_MAP_ENTITY, CONF_VACUUM_ENTITY


class RobertoZonesConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure a single Roberto Zones diagnostic entry."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            await self.async_set_unique_id("roberto_blanko_diagnostics")
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title="Roberto Blanko – Zonendiagnose", data=user_input
            )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_MAP_ENTITY,
                    default="image.wohnzimmer_roberto_blanko_live_map"
                ): str,
                vol.Required(CONF_VACUUM_ENTITY): str,
            }),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return RobertoZonesOptionsFlow()


class RobertoZonesOptionsFlow(config_entries.OptionsFlow):
    """Allow changing source entities."""

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        old = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(CONF_MAP_ENTITY, default=old[CONF_MAP_ENTITY]): str,
                vol.Required(CONF_VACUUM_ENTITY, default=old[CONF_VACUUM_ENTITY]): str,
                vol.Optional("position_entity", default=old.get("position_entity", "")): str,
                vol.Optional("charger_entity", default=old.get("charger_entity", "")): str,
            }),
        )
