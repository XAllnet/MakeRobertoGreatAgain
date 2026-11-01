"""Roberto Zones: event-driven diagnostics and supervised step tests."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import voluptuous as vol
from datetime import datetime, timezone
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
from .native_geometry import extract_native_geometry
from .registration_consensus import RegistrationConsensus
from .manual_test import SupervisedDrive, TEST_STEPS
from .verification import CheckpointSession, candidate_is_usable

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
        self._geometry_reference = Path(hass.config.path("roberto_zones", "reference_geometry.png"))
        self._geometry_meta = Path(hass.config.path("roberto_zones", "reference_geometry.json"))
        self._reference_baseline_active = False
        self.overlay_bytes: bytes | None = None
        self.overlay_time: datetime | None = None
        self.position: dict | None = None
        self.position_source: str | None = None
        self.position_source_last_changed: str | None = None
        self.position_received_at: str | None = None
        self._position_entity: str | None = None
        self._charger_entity: str | None = None
        self.drive = SupervisedDrive(hass, self)
        self.verifier = CheckpointSession()
        self._checkpoints_file = Path(
            hass.config.path("roberto_zones", "checkpoints.json")
        )
        self._latest_overlay_info: dict = {}
        self._registration_consensus = RegistrationConsensus()
        self._seen_map_identity = None

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

    async def async_load_checkpoints(self) -> None:
        """Restore private reference landmarks only when SHA256 still matches."""
        def load():
            if not self._reference.is_file():
                return None
            current_hash = hashlib.sha256(self._reference.read_bytes()).hexdigest()
            if not self._checkpoints_file.is_file():
                return {"reference_hash": current_hash, "points": {}}
            saved = json.loads(self._checkpoints_file.read_text(encoding="utf-8"))
            if not isinstance(saved, dict) or saved.get("reference_hash") != current_hash:
                return {"reference_hash": current_hash, "points": {}}
            points = saved.get("points", {})
            if not isinstance(points, dict):
                return {"reference_hash": current_hash, "points": {}}
            valid = {
                name: {"name": name, "x": int(point["x"]), "y": int(point["y"])}
                for name, point in points.items()
                if isinstance(name, str) and isinstance(point, dict)
                and len(name) <= 32 and name
                and isinstance(point.get("x"), int) and isinstance(point.get("y"), int)
                and 0 <= point["x"] <= 52000 and 0 <= point["y"] <= 52000
            }
            return {"reference_hash": current_hash, "points": valid}

        try:
            saved = await self.hass.async_add_executor_job(load)
            if saved:
                self.verifier.reference_hash = saved["reference_hash"]
                self.verifier.reference_points = saved["points"]
        except (OSError, ValueError, TypeError, KeyError) as err:
            _LOGGER.warning("Could not restore Roberto checkpoint data: %s", err)

    async def async_save_checkpoints(self) -> None:
        """Atomic local-only metadata persistence; no geometry or tokens in GitHub."""
        payload = {
            "schema": 1,
            "reference_hash": self.verifier.reference_hash,
            "points": self.verifier.reference_points,
        }

        def save():
            self._checkpoints_file.parent.mkdir(parents=True, exist_ok=True)
            temp = self._checkpoints_file.with_suffix(".tmp")
            temp.write_text(json.dumps(payload), encoding="utf-8")
            temp.replace(self._checkpoints_file)

        await self.hass.async_add_executor_job(save)

    def _current_map_identity(self):
        state = self.hass.states.get(self.map_entity)
        if state is None:
            return None
        for field in ("map_id", "map_index", "map_name"):
            value = state.attributes.get(field)
            if isinstance(value, (str, int)) and value not in ("", "unknown"):
                return f"{field}:{value}"
        return None

    def _sample_position(self, name: str):
        """Collect source state + timestamps, not the throttled overlay marker."""
        map_state = self.hass.states.get(self.map_entity)
        self._refresh_position(map_state)
        if self.position is None or not self.position_source:
            raise HomeAssistantError("Roboterposition ist nicht verfügbar")
        source = self.hass.states.get(self.position_source)
        if source is None:
            raise HomeAssistantError("Positionsquellen-Entität fehlt")
        last_reported = getattr(source, "last_reported", None)
        source_event_time = last_reported or source.last_updated
        from .verification import MAX_SOURCE_AGE_S
        try:
            return self.verifier.snapshot(
                name, self.position, source_event_time,
                self.position_source,
                datetime.now(timezone.utc)
            )
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err

    def _require_stopped(self):
        vacuum = self.hass.states.get(self.vacuum_entity)
        if vacuum is None or vacuum.state not in ("idle", "docked"):
            raise HomeAssistantError(
                "Vor jeder Messung vollständig anhalten. "
                f"Roboterstatus: {vacuum.state if vacuum else 'nicht verfügbar'}"
            )

    @callback
    def _require_point_name(self, name):
        if not isinstance(name, str) or not (1 <= len(name) <= 32):
            raise HomeAssistantError("Punktname muss 1–32 Zeichen haben")
        if not all(c.isalnum() or c in ("_", "-") for c in name):
            raise HomeAssistantError("Punktnamen nur mit Buchstaben, Zahlen, _ oder -")
        return name

    async def async_record_reference_point(self, name):
        self._require_stopped()
        name = self._require_point_name(name)
        if not self.verifier.baseline_enabled:
            raise HomeAssistantError(
                "Referenzphase nicht aktiv. Erst vollständige Karte mit "
                "roberto_zones.capture_reference sichern"
            )
        if not self._reference_baseline_active:
            raise HomeAssistantError(
                "Die Referenzpunkterfassung muss in derselben laufenden "
                "Home-Assistant-Sitzung wie capture_reference stattfinden."
            )
        if not self._latest_overlay_info.get("geometry_only", False):
            raise HomeAssistantError(
                "Native Geometrie aktuell nicht verfügbar; Punktaufnahme gesperrt"
            )
        stable = self._sample_position(name)
        if stable is None:
            self.verifier.status = "referenz_messung_1_von_2"
            self._notify()
            return
        try:
            self.verifier.store_reference_point(name, stable)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        await self.async_save_checkpoints()
        self._notify()

    async def async_begin_verification(self, new_map_confirmed: bool):
        if new_map_confirmed is not True:
            raise HomeAssistantError("Neuen Kartierungsdurchlauf ausdrücklich bestätigen")
        if not self._reference.is_file() or not self._reference_meta.is_file():
            raise HomeAssistantError("Kalibrierte Originalreferenz fehlt")
        try:
            self.verifier.begin(
                self._latest_overlay_info, self.run_count,
                self._current_map_identity()
            )
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        self._notify()

    async def async_check_checkpoint(self, name):
        name = self._require_point_name(name)
        self._require_stopped()
        self.verifier.check_map(
            self._latest_overlay_info,
            self.run_count,
            self._current_map_identity()
        )
        if not self.verifier.active:
            self._notify()
            raise HomeAssistantError("Kartenzuordnung nicht mehr gültig; Prüfung gesperrt")
        if name not in self.verifier.reference_points:
            raise HomeAssistantError("Diesen Namen gibt es nicht als Referenzpunkt")
        if name in self.verifier.results:
            raise HomeAssistantError("Punkt wurde bereits geprüft")
        stable = self._sample_position(name)
        if stable is None:
            self.verifier.status = "pruefmessung_1_von_2"
            self._notify()
            return
        try:
            self.verifier.verify_point(name, stable)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        self._notify()

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
        self._refresh_position(self.hass.states.get(self.map_entity))
        self._seen_map_identity = self._current_map_identity()
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
                self.verifier.invalidate("neuer_reinigungsvorgang")
                self._reference_baseline_active = False
                self._registration_consensus.reset("neuer_reinigungsvorgang")
                self.run_count += 1
                self.status = "neuer_reinigungsvorgang"
                self.rotation = None
                self._notify()
                self._schedule(DEBOUNCE_SECONDS)
            return
        if new.entity_id in (self._position_entity, self._charger_entity):
            if old is None or old.state != new.state or old.attributes != new.attributes:
                if new.entity_id == self._position_entity:
                    # Lightweight event handler: do not wait for the 15-second
                    # image overlay throttle to update the position sensor.
                    self._refresh_position(self.hass.states.get(self.map_entity))
                    self._notify()
                self._schedule(DEBOUNCE_SECONDS)
            return
        if new.entity_id == self.map_entity and (
            old is None or old.state != new.state or old.attributes != new.attributes
        ):
            identity = self._current_map_identity()
            if (
                self._seen_map_identity is not None
                and identity is not None
                and identity != self._seen_map_identity
            ):
                self._registration_consensus.reset("kartenkennung_gewechselt")
                self.verifier.invalidate("kartenkennung_gewechselt")
                self._reference_baseline_active = False
            if identity is not None:
                self._seen_map_identity = identity
            self.last_map_state = new.state
            # Fallback for older extractors that expose position on the image.
            if not self._position_entity:
                self._refresh_position(new)
                self._notify()
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

    @callback
    def _refresh_position(self, map_state=None) -> None:
        """Copy the most recently reported coordinate without image processing.

        Home Assistant's last_updated is an entity-state timestamp and does
        not guarantee the actual Xiaomi measurement time.
        """
        source = None
        position = None
        changed_at = None
        if self._position_entity:
            state = self.hass.states.get(self._position_entity)
            if state is not None:
                position = parse_position(state.attributes)
                if position is None:
                    position = parse_position(state.state)
                if position is not None:
                    source = self._position_entity
                    changed_at = state.last_updated.isoformat()
        if position is None and map_state is not None:
            position = parse_position(map_state.attributes.get("vacuum_position"))
            if position is not None:
                source = self.map_entity
                changed_at = map_state.last_updated.isoformat()
        self.position = position
        self.position_source = source
        self.position_source_last_changed = changed_at
        self.position_received_at = (
            datetime.now().astimezone().isoformat(timespec="seconds")
            if position is not None else None
        )

    def _cached_native_map(self, image_bytes: bytes):
        """Read the existing Map Extractor coordinator data (no extra cloud IO).

        This is a private alpha-v3 Map Extractor API. Verify ownership,
        versioned structure and image bytes, and otherwise fail closed.
        """
        entity = er.async_get(self.hass).async_get(self.map_entity)
        if entity is None or entity.platform != "xiaomi_cloud_map_extractor":
            return None
        config_entry = self.hass.config_entries.async_get_entry(entity.config_entry_id)
        if config_entry is None or config_entry.domain != "xiaomi_cloud_map_extractor":
            return None
        runtime = getattr(config_entry, "runtime_data", None)
        coordinator = getattr(runtime, "coordinator", None)
        cache = getattr(coordinator, "data", None)
        if (
            cache is None
            or not isinstance(getattr(cache, "map_image", None), bytes)
            or cache.map_image != image_bytes
        ):
            return None
        if (
            not isinstance(getattr(cache, "map_data_raw", None), bytes)
            or getattr(cache, "map_data", None) is None
        ):
            return None
        return cache

    @callback
    def _geometry_unavailable(self, code: str, explanation: str):
        self.status = code
        self.rotation = None
        self._latest_overlay_info = {}
        self.overlay_bytes = None
        self.overlay_time = datetime.now().astimezone()
        self.details = {
            "reason": explanation,
            "geometry_only": True,
            "navigation_coordinates_verified": False,
            "can_send_automatic_targets": False,
        }
        self._registration_consensus.reset(code)
        self.verifier.invalidate(code)

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
            self._refresh_position(state)
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
            current_state = self.hass.states.get(self.map_entity)
            if current_state is None or current_state.state != state.state:
                self.status = "karte_waehrend_auslesen_aktualisiert"
                self._schedule(DEBOUNCE_SECONDS)
                return
            cached = self._cached_native_map(image.content)
            if cached is None:
                self._geometry_unavailable(
                    "native_geometrie_nicht_verfuegbar",
                    "Kein synchroner v3-Map-Extractor-Cache; keine Pixelbild-Heuristik als Ersatz",
                )
                return
            raw_map_snapshot = bytes(cached.map_data_raw)
            map_data_snapshot = cached.map_data
            try:
                live_geometry, live_calibration, geometry_diag = (
                    await self.hass.async_add_executor_job(
                        extract_native_geometry, raw_map_snapshot,
                        map_data_snapshot, calibration,
                    )
                )
            except ValueError as err:
                self._geometry_unavailable(
                    "native_geometrie_nicht_verfuegbar", str(err)
                )
                return
            if not self._geometry_reference.is_file() or not self._geometry_meta.is_file():
                self._geometry_unavailable(
                    "referenz_geometrie_fehlt",
                    "Einmalige neue vollständige Referenz nötig: "
                    "roberto_zones.capture_reference (Version 0.6.3)",
                )
                return

            robot = self._get_map_position(
                self._position_entity, "vacuum_position", state
            )
            charger = self._get_map_position(
                self._charger_entity, "charger", state
            )

            def prepare_overlay():
                reference_geometry = self._geometry_reference.read_bytes()
                reference_original = self._reference.read_bytes()
                stored = json.loads(self._geometry_meta.read_text(encoding="utf-8"))
                if (
                    stored.get("schema") != 3
                    or stored.get("rendered_sha256") != hashlib.sha256(reference_original).hexdigest()
                    or stored.get("geometry_sha256") != hashlib.sha256(reference_geometry).hexdigest()
                ):
                    raise ValueError("Referenzgeometrie und Originalkarte stimmen nicht überein")
                reference_calibration = stored.get("geometry_calibration")
                reference_charger = stored.get("charger_position")
                try:
                    shape_compare = compare(live_geometry, reference_geometry)
                except ValueError:
                    shape_compare = {
                        "candidate_is_distinct": False,
                        "note": "Silhouettenvergleich noch nicht möglich",
                    }
                return (
                    build_overlay(
                        reference_geometry, live_geometry,
                        reference_calibration, live_calibration, robot, charger,
                        reference_charger,
                        preview_gate=self._registration_consensus.can_preview() or {},
                    ),
                    shape_compare,
                )

            (overlay, overlay_info), result = await self.hass.async_add_executor_job(
                prepare_overlay
            )
            # The native geometry and rendered image represent one cached
            # map revision. Never use them if the coordinator has since moved.
            if (
                self._cached_native_map(image.content) is not cached
                or cached.map_data_raw != raw_map_snapshot
                or cached.map_data is not map_data_snapshot
            ):
                self._geometry_unavailable(
                    "karte_waehrend_auslesen_aktualisiert",
                    "Quellkarte wurde während der Berechnung ersetzt",
                )
                self._schedule(DEBOUNCE_SECONDS)
                return
            overlay_info.update(geometry_diag)
            overlay_info["geometry_only"] = True
            overlay_info["no_path_fallback"] = True
            overlay_info["source_image_timestamp"] = state.state
            overlay_info["calibration_points"] = live_calibration
            overlay_info["map_entity"] = self.map_entity
            overlay_info["vacuum_entity"] = self.vacuum_entity
            overlay_info["reference_file_local"] = "roberto_zones/reference_geometry.png"
            overlay_info["charger_entity"] = self._charger_entity
            overlay_info["position_entity"] = self._position_entity
            overlay_info["position_source"] = self.position_source
            overlay_info["position_sensor_last_updated"] = self.position_source_last_changed
            overlay_info["overlay_uses_position_snapshot"] = True
            overlay_info["run_count_observed_since_setup"] = self.run_count
            if not self._closed:
                self.overlay_bytes = overlay
                self.overlay_time = datetime.now().astimezone()
            # Require multiple different, agreeing map silhouettes. A
            # single plausible candidate is NOT an alignment confirmation.
            raw_candidate = overlay_info.get("visual_alignment_candidate", False)
            temporally_stable = self._registration_consensus.observe(overlay_info)
            overlay_info["instant_visual_candidate"] = raw_candidate
            overlay_info["visual_alignment_candidate"] = bool(
                raw_candidate and temporally_stable
            )
            overlay_info.update(self._registration_consensus.info())
            self._latest_overlay_info = overlay_info
            self.verifier.check_map(
                overlay_info, self.run_count, self._current_map_identity()
            )
            self.details = {
                **result,
                **overlay_info,
                "position_entity": self._position_entity,
                "charger_entity": self._charger_entity,
                "position_source": self.position_source,
                "position_sensor_last_updated": self.position_source_last_changed,
                "overlay_uses_position_snapshot": True,
                "map_entity": self.map_entity,
                "vacuum_entity": self.vacuum_entity,
                "calibration_present": calibration is not None,
                "calibration_points": calibration,
                "image_timestamp": state.state,
                "reference_file_local": "roberto_zones/reference.png",
                "run_count_observed_since_setup": self.run_count,
            }
            self.rotation = (
                overlay_info.get("rotation_candidate_degrees")
                if overlay_info.get("visual_alignment_candidate", False)
                else None
            )
            if not overlay_info["reference_calibrated"]:
                self.status = "referenz_ohne_koordinaten"
            elif not overlay_info["live_calibrated"]:
                self.status = "live_kalibrierung_fehlt"
            elif not overlay_info.get("visual_alignment_candidate", False):
                self.status = (
                    "ausrichtung_noch_nicht_stabil"
                    if raw_candidate and not temporally_stable
                    else "ausrichtung_nicht_bestaetigt"
                )
            elif overlay_info.get("anchor_assumed", True):
                self.status = "anker_nicht_bestaetigt"
            elif not robot:
                self.status = "position_nicht_verfuegbar"
            else:
                self.status = "ueberlagerung_plausibel_pruefung_offen"
            # Refresh again in case the position entity changed while
            # the slow map rendering was running in the executor.
            self._refresh_position(self.hass.states.get(self.map_entity))
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
        current_state = self.hass.states.get(self.map_entity)
        if current_state is None or current_state.state != state.state:
            raise HomeAssistantError(
                "Die Live-Karte hat sich während der Aufnahme geändert. "
                "Bitte erneut versuchen."
            )
        raw = image.content
        if not raw or len(raw) > 10_000_000:
            raise HomeAssistantError("Kartendatei leer oder ungewöhnlich groß")

        calibration = state.attributes.get("calibration_points")
        cached = self._cached_native_map(raw)
        if cached is None:
            raise HomeAssistantError(
                "Die native Geometrie aus dem Map-Extractor-Cache fehlt; "
                "Referenz wurde nicht überschrieben."
            )
        raw_map_snapshot = bytes(cached.map_data_raw)
        map_data_snapshot = cached.map_data
        try:
            native_bytes, native_calibration, native_info = (
                await self.hass.async_add_executor_job(
                    extract_native_geometry, raw_map_snapshot,
                    map_data_snapshot, calibration
                )
            )
        except ValueError as err:
            raise HomeAssistantError(
                f"Native Referenzgeometrie kann nicht erfasst werden: {err}"
            ) from err
        if (
            self._cached_native_map(raw) is not cached
            or cached.map_data_raw != raw_map_snapshot
            or cached.map_data is not map_data_snapshot
        ):
            raise HomeAssistantError(
                "Karte während der Aufnahme aktualisiert; bitte erneut versuchen"
            )
        charger_position = self._get_map_position(
            self._charger_entity, "charger", state
        )

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
                "charger_position": charger_position,
            }
            meta_tmp = self._reference_meta.with_suffix(".tmp")
            meta_tmp.write_text(json.dumps(values), encoding="utf-8")
            meta_tmp.replace(self._reference_meta)
            geometry_tmp = self._geometry_reference.with_suffix(".tmp")
            geometry_tmp.write_bytes(native_bytes)
            geometry_tmp.replace(self._geometry_reference)
            geometry_metadata = {
                "schema": 3,
                "rendered_sha256": hashlib.sha256(raw).hexdigest(),
                "geometry_sha256": native_info["geometry_sha256"],
                "geometry_calibration": native_calibration,
                "charger_position": charger_position,
                "source": "cached_roborock_raw_image_block",
                "contains_robot_path": False,
                "contains_robot_marker": False,
            }
            meta_geometry_tmp = self._geometry_meta.with_suffix(".tmp")
            meta_geometry_tmp.write_text(
                json.dumps(geometry_metadata), encoding="utf-8"
            )
            meta_geometry_tmp.replace(self._geometry_meta)

        await self.hass.async_add_executor_job(save)
        self._registration_consensus.reset("neue_referenz")
        self.verifier.initialize_reference(hashlib.sha256(raw).hexdigest())
        self._reference_baseline_active = True
        await self.async_save_checkpoints()
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
            self._geometry_reference.unlink(missing_ok=True)
            self._geometry_meta.unlink(missing_ok=True)
            return metadata

        try:
            metadata = await self.hass.async_add_executor_job(read_prepare_and_write)
        except (OSError, ValueError) as exc:
            raise HomeAssistantError(f"Referenzimport fehlgeschlagen: {exc}") from exc
        self._registration_consensus.reset("neue_referenz")
        self._reference_baseline_active = False
        self.verifier.invalidate("referenz_ohne_kalibrierung_importiert")
        self.verifier.reference_points.clear()
        self.verifier.reference_hash = None
        await self.async_save_checkpoints()
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
    await controller.async_load_checkpoints()
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

    async def record_reference_point(call):
        await controller.async_record_reference_point(call.data["name"])

    async def begin_verification(call):
        await controller.async_begin_verification(call.data["new_map_confirmed"])

    async def verify_checkpoint(call):
        await controller.async_check_checkpoint(call.data["name"])

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
    checkpoint_schema = vol.Schema({
        vol.Required("name"): vol.All(str, vol.Length(min=1, max=32)),
        vol.Required("physical_confirmation"): vol.Equal(True),
    })
    hass.services.async_register(
        DOMAIN, "record_reference_point", record_reference_point,
        schema=checkpoint_schema,
    )
    hass.services.async_register(
        DOMAIN, "begin_verification", begin_verification,
        schema=vol.Schema({
            vol.Required("new_map_confirmed"): vol.Equal(True),
        }),
    )
    hass.services.async_register(
        DOMAIN, "verify_checkpoint", verify_checkpoint,
        schema=checkpoint_schema,
    )
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
        hass.services.async_remove(DOMAIN, "record_reference_point")
        hass.services.async_remove(DOMAIN, "begin_verification")
        hass.services.async_remove(DOMAIN, "verify_checkpoint")
    return success
