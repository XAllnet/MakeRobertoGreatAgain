"""Explicit, short, supervised Miio steering tests.

No map coordinates, automatic movements, recurring tasks or vacuum cleaning.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

_LOGGER = logging.getLogger(__name__)

# Small single steps: velocity in m/s, rotation in degrees, duration in ms.
# Each step automatically stops remote-control mode (Xiaomi Miio service).
TEST_STEPS = {
    "forward":  {"velocity": 0.12, "rotation": 0,   "duration": 600},
    "backward": {"velocity": -0.10, "rotation": 0,  "duration": 500},
    "left":     {"velocity": 0.10, "rotation": -35,"duration": 500},
    "right":    {"velocity": 0.10, "rotation": 35, "duration": 500},
}

SERVICE_DOMAIN = "xiaomi_miio"
SERVICE_STEP = "vacuum_remote_control_move_step"
SERVICE_REMOTE_STOP = "vacuum_remote_control_stop"


class SupervisedDrive:
    """No background processing; command only from an explicit service call."""

    def __init__(self, hass: HomeAssistant, controller) -> None:
        self.hass = hass
        self.controller = controller
        self._lock = asyncio.Lock()
        self._last_sent = 0.0
        self.status = "nicht_getestet"
        self.last_test: str | None = None
        self.last_command: str | None = None
        self.last_error: str | None = None

    def _notify(self) -> None:
        self.controller._notify()

    def _validate_miio_entity(self) -> str:
        entity_id = self.controller.vacuum_entity
        if not entity_id.startswith("vacuum."):
            raise HomeAssistantError("Konfigurierte Entität ist kein Staubsauger")
        registered = er.async_get(self.hass).async_get(entity_id)
        if not registered or not registered.config_entry_id:
            raise HomeAssistantError("Die lokale Xiaomi-Miio-Entität wurde nicht gefunden")
        parent = self.hass.config_entries.async_get_entry(registered.config_entry_id)
        if parent is None or parent.domain != SERVICE_DOMAIN:
            raise HomeAssistantError(
                "Bitte in Roberto Zones die lokale Xiaomi-Miio-Entität konfigurieren "
                "(nicht Xiaomi Home von Xiaomi)"
            )
        return entity_id

    async def async_move_step(self, direction: str, supervised: bool) -> None:
        if supervised is not True:
            raise HomeAssistantError(
                "Testfahrten nur unter unmittelbarer Aufsicht auf freier Fläche"
            )
        if self._lock.locked():
            raise HomeAssistantError("Ein Fahrbefehl wird bereits ausgeführt")
        if direction not in TEST_STEPS:
            raise HomeAssistantError("Unbekannte Testrichtung")
        if not self.hass.services.has_service(SERVICE_DOMAIN, SERVICE_STEP):
            raise HomeAssistantError(
                "Die Aktion xiaomi_miio.vacuum_remote_control_move_step fehlt"
            )
        entity = self._validate_miio_entity()
        current = self.hass.states.get(entity)
        if current is None or current.state not in ("idle", "docked"):
            raise HomeAssistantError(
                "Test nur bei stehendem Roboter im Status idle oder docked; "
                f"aktueller Status: {current.state if current else 'unbekannt'}"
            )
        if time.monotonic() - self._last_sent < 3.0:
            raise HomeAssistantError("Zwischen Testbewegungen mindestens 3 Sekunden lassen")

        async with self._lock:
            # Last validation immediately before dispatch.
            now_state = self.hass.states.get(entity)
            if now_state is None or now_state.state not in ("idle", "docked"):
                raise HomeAssistantError("Roboter ist nicht mehr im Ruhezustand")
            self._last_sent = time.monotonic()
            self.status = "befehl_wird_gesendet"
            self.last_error = None
            self._notify()
            try:
                await asyncio.wait_for(
                    self.hass.services.async_call(
                        SERVICE_DOMAIN,
                        SERVICE_STEP,
                        TEST_STEPS[direction],
                        target={"entity_id": entity},
                        blocking=True,
                    ),
                    timeout=15,
                )
            except Exception as err:
                self.status = "testfahrt_fehlgeschlagen"
                self.last_error = f"{type(err).__name__}: {str(err)[:180]}"
                _LOGGER.warning("Roberto step motion failed: %s", err)
                self._notify()
                raise HomeAssistantError(
                    "Testbewegung fehlgeschlagen. Bitte Robertos Zustand kontrollieren. "
                    f"Details: {type(err).__name__}"
                ) from err

            self.status = "befehl_angenommen"
            self.last_command = direction
            self.last_test = datetime.now().astimezone().isoformat(timespec="seconds")
            self._notify()

    async def async_stop(self) -> None:
        """Manual emergency stop; no automatic docking/cleaning."""
        entity = self._validate_miio_entity()
        errors = []
        # HA vacuum.stop is also valid when robot is not in remote mode.
        try:
            await asyncio.wait_for(
                self.hass.services.async_call(
                    "vacuum",
                    "stop",
                    target={"entity_id": entity},
                    blocking=True,
                ),
                timeout=10,
            )
        except Exception as err:
            errors.append(f"vacuum.stop: {type(err).__name__}")
        if self.hass.services.has_service(SERVICE_DOMAIN, SERVICE_REMOTE_STOP):
            try:
                await asyncio.wait_for(
                    self.hass.services.async_call(
                        SERVICE_DOMAIN,
                        SERVICE_REMOTE_STOP,
                        target={"entity_id": entity},
                        blocking=True,
                    ),
                    timeout=10,
                )
            except Exception as err:
                errors.append(f"remote_control_stop: {type(err).__name__}")
        self.last_test = datetime.now().astimezone().isoformat(timespec="seconds")
        self.status = "stop_gesendet" if not errors else "stop_nicht_bestaetigt"
        self.last_error = "; ".join(errors) if errors else None
        self._notify()
        if errors:
            raise HomeAssistantError(
                "Stop konnte nicht vollständig bestätigt werden. "
                "Roboter vor Ort über die physische Taste stoppen."
            )
