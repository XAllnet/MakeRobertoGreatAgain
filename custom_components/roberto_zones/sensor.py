"""Read-only diagnostic sensors for Roberto Zones."""
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import callback

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    controller = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        RobertoDiagnosticSensor(controller),
        RobertoOrientationSensor(controller),
    ])


class _BaseSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_icon = "mdi:map-search"

    def __init__(self, controller):
        self.controller = controller
        self._attr_device_info = {
            "identifiers": {(DOMAIN, "roberto_zones_diagnostic")},
            "name": "Roberto Zones",
            "manufacturer": "Eigenentwicklung (lokal)",
            "model": "0.1 Diagnose – schreibgeschützt",
        }

    async def async_added_to_hass(self):
        self.controller.on_change.append(self._changed)

    async def async_will_remove_from_hass(self):
        if self._changed in self.controller.on_change:
            self.controller.on_change.remove(self._changed)

    @callback
    def _changed(self):
        self.async_write_ha_state()


class RobertoDiagnosticSensor(_BaseSensor):
    _attr_name = "Kartenstatus"
    _attr_unique_id = "roberto_zones_map_status_v1"

    @property
    def native_value(self):
        return self.controller.status

    @property
    def extra_state_attributes(self):
        d = dict(self.controller.details)
        d["last_analysis"] = self.controller.last_analysis
        d["automatic_zone_commands_enabled"] = False
        d["no_go_zones_enforced"] = False
        d["read_only"] = True
        return d


class RobertoOrientationSensor(_BaseSensor):
    _attr_name = "Orientierungskandidat"
    _attr_icon = "mdi:compass-outline"
    _attr_unique_id = "roberto_zones_orientation_candidate_v1"
    _attr_native_unit_of_measurement = "°"

    @property
    def native_value(self):
        return self.controller.rotation

    @property
    def extra_state_attributes(self):
        return {"verified_for_navigation": False}
