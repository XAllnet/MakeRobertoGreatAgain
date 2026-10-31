"""Map diagnostic sensors and supervised drive status for Roberto Zones."""
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import callback

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    controller = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        RobertoDiagnosticSensor(controller),
        RobertoOrientationSensor(controller),
        RobertoTestDriveSensor(controller),
        RobertoPositionSensor(controller),
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
            "model": "0.5.1 Positionsdiagnose und Kartenüberlagerung",
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
        d["read_only"] = False
        d["automatic_drive_enabled"] = False
        d["manual_step_only"] = True
        d["real_world_position_verified"] = False
        d["overlay_is_not_navigation_authorization"] = True
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


class RobertoTestDriveSensor(_BaseSensor):
    _attr_name = "Manuelle Testfahrt"
    _attr_icon = "mdi:robot-vacuum"
    _attr_unique_id = "roberto_zones_manual_test_v1"

    @property
    def native_value(self):
        return self.controller.drive.status

    @property
    def extra_state_attributes(self):
        return {
            "last_test": self.controller.drive.last_test,
            "last_command": self.controller.drive.last_command,
            "last_error": self.controller.drive.last_error,
            "fan_cleaning_command_sent": False,
            "no_go_zones_enforced": False,
            "requires_supervision": True,
        }


class RobertoPositionSensor(_BaseSensor):
    _attr_name = "Roboterposition (Xiaomi-Koordinaten)"
    _attr_icon = "mdi:crosshairs-gps"
    _attr_unique_id = "roberto_zones_robot_position_v1"

    @property
    def native_value(self):
        pos = self.controller.position
        if pos is None:
            return "nicht_verfuegbar"
        return f'{pos["x"]}, {pos["y"]}'

    @property
    def extra_state_attributes(self):
        pos = self.controller.position
        return {
            "x_mm": pos["x"] if pos else None,
            "y_mm": pos["y"] if pos else None,
            "angle": pos.get("angle") if pos else None,
            "source": self.controller.position_source,
            "source_entity_last_updated": self.controller.position_source_last_changed,
            "received_by_roberto_zones_at": self.controller.position_received_at,
            "source_update_time_is_not_measurement_time": True,
            "map_overlay_updates_separately": True,
            "physical_location_confirmed": False,
            "auto_navigation_enabled": False,
        }
