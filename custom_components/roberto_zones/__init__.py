"""Roberto Zones: event-driven diagnostics and supervised step tests."""
from __future__ import annotations

import asyncio
import hashlib
import json
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
from homeassistant.helpers import entity_registry as er

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
from .world_overlay import build_overlay, parse_position
from .manual_test import SupervisedDrive, TEST_STEPS

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR, Platform.IMAGE]


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
        self._reference_meta = Path(hass.config.path("roberto_zones", "reference_calibration.json"))
        self.overlay_bytes: bytes | None = None
        self.overlay_time: datetime | None = None
        self.position: dict | None = None
        self.position_source: str | None = None
        self._position_entity: str | None = None
        self._charger_entity: str | None = None
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

    def _source_entity(self, option_name: str, key: str) -> str | None:
        """Find map extractor v3 diagnostic entities from the map's entry."""
        specified = self.entry.options.get(option_name, "")
        if specified:
            return specified
        registry = er.async_get(self.hass)
        map_entry = registry.async_get(self.map_entity)
        if map_entry is None or not map_entry.config_entry_id:
            return None
        candidates = [
            ent.entity_id
            for ent in registry.entities.values()
            if ent.config_entry_id == map_entry.config_entry_id
            and ent.platform == "xiaomi_cloud_map_extractor"
            and (ent.unique_id.endswith(key) or ent.entity_id.endswith(key))
        ]
        return sorted(candidates)[0] if candidates else None

    async def async_start(self) -> None:
        self._position_entity = self._source_entity("position_entity", "vacuum_position")
        self._charger_entity = self._source_entity("charger_entity", "charger_position")
        entities = [self.map_entity, self.vacuum_entity]
        for entity in (self._position_entity, self._charger_entity):
            if entity and entity not in entities:
                entities.append(entity)
        self.listeners.append(async_track_state_change_event(
            self.hass, entities, self._handle_change
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
                self._schedule(DEBOUNCE_SECONDS)
            return
        if new.entity_id in (self._position_entity, self._charger_entity):
            if old is None or old.state != new.state:
                self._schedule(DEBOUNCE_SECONDS)
            return
        if new.entity_id == self.map_entity and (
            old is None or old.state != new.state
        ):
            self.last_map_state = new.state
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

    def _get_map_position(self, entity_id: str | None, key: str, map_state):
        if entity_id:
            state = self.hass.states.get(entity_id)
            if state is not None:
                position = parse_position(state.attributes)
                if position is None:
                    position = parse_position(state.state)
                if position is not None:
                    return position
        return parse_position(map_state.attributes.get(key))

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
            try:
                result = await self.hass.async_add_executor_job(
                    compare, image.content, reference_bytes
                )
            except ValueError:
                result = {"candidate_is_distinct": False,
                          "note": "Silhouettenvergleich noch nicht möglich"}
            robot = self._get_map_position(self._position_entity, "vacuum_position", state)
            charger = self._get_map_position(self._charger_entity, "charger", state)
            self.position = robot
            self.position_source = (
                self._position_entity if robot and self._position_entity
                else ("legacy_image_attribute" if robot else None)
            )

            def prepare_overlay():
                reference_calibration = None
                if self._reference_meta.is_file():
                    stored = json.loads(self._reference_meta.read_text(encoding="utf-8"))
                    if stored.get("sha256") == hashlib.sha256(reference_bytes).hexdigest():
                        reference_calibration = stored.get("calibration_points")
                return build_overlay(
                    reference_bytes, image.content, reference_calibration,
                    calibration, robot, charger,
                )

            overlay, overlay_info = await self.hass.async_add_executor_job(
                prepare_overlay
            )
            if not self._closed:
                self.overlay_bytes = overlay
                self.overlay_time = datetime.now().astimezone()
            self.details = {
                **result,
                **overlay_info,
                "position_entity": self._position_entity,
                "charger_entity": self._charger_entity,
                "position_source": self.position_source,
                "map_entity": self.map_entity,
                "vacuum_entity": self.vacuum_entity,
                "calibration_present": calibration is not None,
                "calibration_points": calibration,
                "image_timestamp": state.state,
                "reference_file_local": "roberto_zones/reference.png",
                "run_count_observed_since_setup": self.run_count,
            }
            self.rotation = (
                result.get("candidate_rotation_degrees")
                if result.get("candidate_is_distinct") else None
            )
            if not overlay_info["reference_calibrated"]:
                self.status = "referenz_ohne_koordinaten"
            elif not overlay_info["live_calibrated"]:
                self.status = "live_kalibrierung_fehlt"
            elif not overlay_info.get("visual_alignment_candidate", False):
                self.status = "ausrichtung_nicht_bestaetigt"
            elif not robot:
                self.status = "position_nicht_verfuegbar"
            else:
                self.status = "ueberlagerung_plausibel_pruefung_offen"
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
            # Capture the exact image calibration alongside its hash; never
            # borrow calibration from a different reference image or run.
            calibration = state.attributes.get("calibration_points")
            values = {
                "schema": 1,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "calibration_points": calibration if isinstance(calibration, list) else None,
                "source": self.map_entity,
            }
            meta_tmp = self._reference_meta.with_suffix(".tmp")
            meta_tmp.write_text(json.dumps(values), encoding="utf-8")
            meta_tmp.replace(self._reference_meta)

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
            # A historical screenshot has no trustworthy world calibration.
            self._reference_meta.unlink(missing_ok=True)
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
