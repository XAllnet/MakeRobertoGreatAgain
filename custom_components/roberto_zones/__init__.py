"""Roberto Zones: event-driven diagnostics and supervised step tests."""
from __future__ import annotations

import asyncio
import logging
import time
import voluptuous as vol
from datetime import datetime
from pathlib import Path

from homeassistant.components.image import async_get_image
from homeassistant.components.media_source import async_resolve_media, Unresolvable
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later, async_track_state_change_event

from .const import (
    CONF_MAP_ENTITY,
    CONF_VACUUM_ENTITY,
    DEBOUNCE_SECONDS,
    DOMAIN,
    MIN_INTERVAL_SECONDS,
    SERVICE_ANALYZE,
)
from .matcher import compare
from .reference_image import prepare_reference_image, MAX_INPUT_BYTES
from .manual_test import SupervisedDrive, TEST_STEPS

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR]


class RobertoController:
    """Read-only diagnostics with throttling and no periodic polling."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.status = "wartet_auf_karte"
        self.rotation = None
        self.details: dict = {}
        self.last_analysis: str | None = None
        self.run_count = 0
        self.last_map_state: str | None = None
        self.listeners = []
        self.on_change: list = []
        self._cancel_debounce = None
        self._running = False
        self._pending = False
        self._last_run_monotonic = 0.0
        self._closed = False
        self._reference = Path(hass.config.path("roberto_zones", "reference.png"))
        self.drive = SupervisedDrive(hass, self)

    @property
    def map_entity(self):
        return self.entry.options.get(
            CONF_MAP_ENTITY, self.entry.data[CONF_MAP_ENTITY]
        )

    @property
    def vacuum_entity(self):
        return self.entry.options.get(
            CONF_VACUUM_ENTITY, self.entry.data[CONF_VACUUM_ENTITY]
        )

    async def async_start(self) -> None:
        self.listeners.append(async_track_state_change_event(
            self.hass, [self.map_entity, self.vacuum_entity], self._handle_change
        ))
        self._schedule(4.0)

    @callback
    def _notify(self) -> None:
        for listener in tuple(self.on_change):
            listener()

    @callback
    def _handle_change(self, event) -> None:
        old = event.data.get("old_state")
        new = event.data.get("new_state")
        if new is None or self._closed:
            return
        if new.entity_id == self.vacuum_entity:
            if new.state == "cleaning" and (old is None or old.state != "cleaning"):
                self.run_count += 1
                self.status = "neuer_reinigungsvorgang"
                self.rotation = None
                self._notify()
            return
        if new.entity_id == self.map_entity and (
            old is None or old.state != new.state
        ):
            self.last_map_state = new.state
            vacuum = self.hass.states.get(self.vacuum_entity)
            if vacuum and vacuum.state == "cleaning":
                self._schedule(DEBOUNCE_SECONDS)

    @callback
    def _schedule(self, delay: float) -> None:
        if self._closed:
            return
        if self._running:
            self._pending = True
            return
        if self._cancel_debounce is not None:
            self._cancel_debounce()
        wait = max(
            delay,
            MIN_INTERVAL_SECONDS - (time.monotonic() - self._last_run_monotonic),
        )
        self._cancel_debounce = async_call_later(
            self.hass, max(0, wait), self._handle_due
        )

    @callback
    def _handle_due(self, _now: datetime) -> None:
        self._cancel_debounce = None
        self.hass.async_create_task(self.async_analyze())

    async def async_analyze(self) -> None:
        if self._closed:
            return
        if self._running:
            self._pending = True
            return
        self._running = True
        self._last_run_monotonic = time.monotonic()
        try:
            state = self.hass.states.get(self.map_entity)
            if state is None:
                self.status = "kartenentitaet_nicht_gefunden"
                self.details = {"map_entity": self.map_entity}
                return
            if not self._reference.is_file():
                self.status = "referenz_fehlt"
                self.details = {
                    "hint": "Vollständige Karte abwarten und roberto_zones.capture_reference manuell ausführen",
                    "read_only": True,
                }
                self.rotation = None
                return
            calibration = state.attributes.get("calibration_points")
            if not isinstance(calibration, list) or len(calibration) < 3:
                calibration = None
            image = await async_get_image(self.hass, self.map_entity, timeout=12)
            reference_bytes = await self.hass.async_add_executor_job(
                self._reference.read_bytes
            )
            result = await self.hass.async_add_executor_job(
                compare, image.content, reference_bytes
            )
            self.details = {
                **result,
                "map_entity": self.map_entity,
                "vacuum_entity": self.vacuum_entity,
                "calibration_present": calibration is not None,
                "calibration_points": calibration,
                "image_timestamp": state.state,
                "reference_file_local": "roberto_zones/reference.png",
                "run_count_observed_since_setup": self.run_count,
            }
            self.rotation = (
                result["candidate_rotation_degrees"]
                if result["candidate_is_distinct"] else None
            )
            self.status = (
                "kandidat_nicht_verifiziert"
                if self.rotation is not None else "orientierung_unklar"
            )
            self.last_analysis = datetime.now().astimezone().isoformat(
                timespec="seconds"
            )
        except (OSError, ValueError, HomeAssistantError, asyncio.TimeoutError) as err:
            self.status = "analyse_fehlgeschlagen"
            self.details = {
                "error_type": type(err).__name__,
                "reason": str(err)[:220],
            }
            _LOGGER.warning("Roberto image diagnostics failed: %s", err)
        except Exception:
            self.status = "analyse_fehlgeschlagen"
            self.details = {"error_type": "UnexpectedError"}
            _LOGGER.exception("Unexpected Roberto Zones analysis error")
        finally:
            self._running = False
            self._notify()
            if self._pending and not self._closed:
                self._pending = False
                self._schedule(DEBOUNCE_SECONDS)

    async def async_capture_reference(self) -> None:
        """Save the current image locally, only by explicit user command."""
        if self._closed:
            raise HomeAssistantError("Roberto Zones ist nicht aktiv")
        if self._running:
            raise HomeAssistantError("Eine Kartenanalyse läuft bereits")
        state = self.hass.states.get(self.map_entity)
        if state is None or state.state in ("unavailable", "unknown"):
            raise HomeAssistantError("Live-Karte ist nicht verfügbar")
        image = await async_get_image(self.hass, self.map_entity, timeout=12)
        raw = image.content
        if not raw or len(raw) > 10_000_000:
            raise HomeAssistantError("Kartendatei leer oder ungewöhnlich groß")

        def save() -> None:
            self._reference.parent.mkdir(parents=True, exist_ok=True)
            temp = self._reference.with_suffix(".tmp")
            temp.write_bytes(raw)
            temp.replace(self._reference)

        await self.hass.async_add_executor_job(save)
        self.status = "referenz_gespeichert"
        self.details = {
            "reference_file_local": "roberto_zones/reference.png",
            "saved_bytes": len(raw),
        }
        self._notify()
        await self.async_analyze()

    async def async_import_reference(self, selected_media: dict) -> None:
        """Import a historical screenshot using Home Assistant image upload."""
        if self._closed or self._running:
            raise HomeAssistantError("Roberto Zones ist beschäftigt oder nicht aktiv")
        media_id = selected_media.get("media_content_id")
        if not isinstance(media_id, str) or not media_id.startswith(
            "media-source://image_upload/"
        ) or len(media_id) > 256:
            raise HomeAssistantError(
                "Bitte über das Bild-Upload-Feld eine PNG/JPG-Datei auswählen"
            )
        try:
            media = await async_resolve_media(
                self.hass, media_id, target_media_player=None
            )
        except (Unresolvable, ValueError, KeyError) as exc:
            raise HomeAssistantError("Das hochgeladene Bild ist nicht verfügbar") from exc
        if media.path is None:
            raise HomeAssistantError("Die ausgewählte Datei liegt nicht lokal")

        def read_prepare_and_write() -> dict:
            path = Path(media.path)
            if path.stat().st_size > MAX_INPUT_BYTES:
                raise ValueError("Bild ist größer als 10 MB")
            image_bytes, metadata = prepare_reference_image(path.read_bytes())
            self._reference.parent.mkdir(parents=True, exist_ok=True)
            temp = self._reference.with_suffix(".tmp")
            temp.write_bytes(image_bytes)
            temp.replace(self._reference)
            return metadata

        try:
            metadata = await self.hass.async_add_executor_job(read_prepare_and_write)
        except (OSError, ValueError) as exc:
            raise HomeAssistantError(f"Referenzimport fehlgeschlagen: {exc}") from exc
        self.rotation = None
        self.details = {
            "import_method": metadata["method"],
            "reference_width": metadata["width"],
            "reference_height": metadata["height"],
            "reference_file_local": "roberto_zones/reference.png",
            "navigation_coordinates_verified": False,
            "warning": "Historischer Screenshot, keine Roboterkoordinaten",
        }
        self.status = "historische_referenz_importiert"
        self._notify()
        await self.async_analyze()

    async def async_stop(self) -> None:
        self._closed = True
        if self._cancel_debounce is not None:
            self._cancel_debounce()
            self._cancel_debounce = None
        for unsub in self.listeners:
            unsub()
        self.listeners.clear()


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    controller = RobertoController(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = controller
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await controller.async_start()

    async def analyze_now(_call):
        await controller.async_analyze()

    async def capture_reference(_call):
        await controller.async_capture_reference()

    async def import_reference(call):
        await controller.async_import_reference(call.data["image"])

    async def test_move_step(call):
        await controller.drive.async_move_step(
            call.data["direction"], call.data["supervised"]
        )

    async def stop_test_drive(_call):
        await controller.drive.async_stop()

    hass.services.async_register(DOMAIN, SERVICE_ANALYZE, analyze_now)
    hass.services.async_register(DOMAIN, "capture_reference", capture_reference)
    hass.services.async_register(
        DOMAIN,
        "import_reference",
        import_reference,
        schema=vol.Schema({vol.Required("image"): dict}),
    )
    hass.services.async_register(
        DOMAIN,
        "test_move_step",
        test_move_step,
        schema=vol.Schema({
            vol.Required("direction"): vol.In(tuple(TEST_STEPS)),
            vol.Required("supervised"): vol.Equal(True),
        }),
    )
    hass.services.async_register(DOMAIN, "stop_test_drive", stop_test_drive)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    success = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if success:
        controller = hass.data[DOMAIN].pop(entry.entry_id)
        await controller.async_stop()
        hass.services.async_remove(DOMAIN, SERVICE_ANALYZE)
        hass.services.async_remove(DOMAIN, "capture_reference")
        hass.services.async_remove(DOMAIN, "import_reference")
        hass.services.async_remove(DOMAIN, "test_move_step")
        hass.services.async_remove(DOMAIN, "stop_test_drive")
    return success
