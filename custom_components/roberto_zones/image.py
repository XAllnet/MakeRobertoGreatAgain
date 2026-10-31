"""A cached local image showing Roberto reference/live map diagnostics."""
from datetime import datetime

from homeassistant.components.image import ImageEntity

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([RobertoMapOverlay(hass, hass.data[DOMAIN][entry.entry_id])])


class RobertoMapOverlay(ImageEntity):
    _attr_has_entity_name = True
    _attr_name = "Referenz und Live-Karte"
    _attr_unique_id = "roberto_zones_overlay_image_v1"
    _attr_should_poll = False

    def __init__(self, hass, controller):
        super().__init__(hass)
        self.controller = controller
        self.content_type = "image/png"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, "roberto_zones_diagnostic")},
            "name": "Roberto Zones",
        }

    def image(self):
        return self.controller.overlay_bytes

    @property
    def image_last_updated(self) -> datetime | None:
        return self.controller.overlay_time

    async def async_added_to_hass(self):
        self.controller.on_change.append(self._updated)

    async def async_will_remove_from_hass(self):
        if self._updated in self.controller.on_change:
            self.controller.on_change.remove(self._updated)

    def _updated(self):
        self.async_write_ha_state()
