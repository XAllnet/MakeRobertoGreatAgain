"""Independent, operator-confirmed landmark checks for Xiaomi map sessions.

No commands are ever sent to a robot from this module. A map-fit alone
cannot establish real-world navigation safety.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

REQUIRED_POINTS = 3
MAX_RESIDUAL_MM = 250
MAX_STATIONARY_DRIFT_MM = 120
MIN_SAMPLE_SEPARATION_S = 8
MAX_SOURCE_AGE_S = 45
MIN_POINT_SPACING_MM = 1000
MIN_TRIANGLE_AREA_MM2 = 500_000


def reference_spread_ok(checkpoints):
    """Require non-collinear, physically separated reference landmarks."""
    points = [(float(x["x"]), float(x["y"])) for x in checkpoints]
    if len(points) < REQUIRED_POINTS:
        return False
    # At least three separate landmarks, with a meaningful 2-D footprint.
    from itertools import combinations
    for a, b, c in combinations(points, 3):
        if min(
            math.dist(a, b), math.dist(a, c), math.dist(b, c)
        ) < MIN_POINT_SPACING_MM:
            continue
        area = abs(
            (b[0]-a[0])*(c[1]-a[1]) -
            (b[1]-a[1])*(c[0]-a[0])
        ) / 2
        if area >= MIN_TRIANGLE_AREA_MM2:
            return True
    return False


def projected_reference_point(live_pos, candidate_matrix):
    """Apply a 3x3 live-Xiaomi-world -> reference-Xiaomi-world transform."""
    if not isinstance(candidate_matrix, list) or len(candidate_matrix) != 3:
        raise ValueError("Keine gültige Transformation")
    rows = candidate_matrix
    if any(not isinstance(row, list) or len(row) != 3 for row in rows):
        raise ValueError("Unvollständige Transformationsmatrix")
    x, y = float(live_pos["x"]), float(live_pos["y"])
    px = sum(float(a)*b for a,b in zip(rows[0], (x,y,1)))
    py = sum(float(a)*b for a,b in zip(rows[1], (x,y,1)))
    pw = sum(float(a)*b for a,b in zip(rows[2], (x,y,1)))
    if not all(map(math.isfinite, (px,py,pw))) or abs(pw) < 1e-8:
        raise ValueError("Ungültige Projektionskoordinaten")
    return {"x": px/pw, "y": py/pw}


def candidate_is_usable(candidate):
    return (
        isinstance(candidate, dict)
        and candidate.get("overlay_mode") == "rotation_corrected_diagnostic"
        and candidate.get("visual_alignment_candidate") is True
        and candidate.get("anchor_assumed") is False
        and candidate.get("reference_calibrated") is True
        and candidate.get("live_calibrated") is True
        and isinstance(candidate.get("rotation_candidate_degrees"), int)
        and isinstance(candidate.get("candidate_transform_live_to_reference"), list)
    )


class CheckpointSession:
    """Transient, fail-closed verification state for one observed map run."""

    def __init__(self):
        self.reference_hash: str | None = None
        self.reference_points: dict[str, dict] = {}
        self.baseline_enabled = False
        self.active = False
        self.status = "nicht_gestartet"
        self.reason = None
        self.pending = {}
        self.results = {}
        self.run_generation: int | None = None
        self.rotation: int | None = None
        self.transform: list | None = None
        self.transform_shift: list | None = None
        self.map_identity = None

    def initialize_reference(self, reference_hash):
        """Called after capturing a new original, calibrated source map."""
        self.invalidate("neue_referenz_gespeichert")
        self.reference_hash = reference_hash
        self.reference_points = {}
        self.baseline_enabled = True
        self.status = "referenzpunkte_erfassen"

    def invalidate(self, reason):
        self.active = False
        self.baseline_enabled = False
        self.pending.clear()
        self.results.clear()
        self.transform = None
        self.rotation = None
        self.transform_shift = None
        self.run_generation = None
        self.map_identity = None
        self.status = "gesperrt"
        self.reason = reason

    def begin(self, candidate, run_generation, map_identity=None):
        if self.baseline_enabled:
            raise ValueError(
                "Referenzaufnahme noch aktiv; erst nach einer neuen Kartierung prüfen"
            )
        if len(self.reference_points) < REQUIRED_POINTS:
            raise ValueError("Mindestens drei Referenzpunkte fehlen")
        if not reference_spread_ok(self.reference_points.values()):
            raise ValueError("Referenzpunkte liegen zu nah beieinander oder auf einer Linie")
        if not candidate_is_usable(candidate):
            raise ValueError("Bildausrichtung oder Dock-Anker noch nicht eindeutig")
        self.pending.clear()
        self.results.clear()
        self.baseline_enabled = False
        self.active = True
        self.run_generation = run_generation
        self.rotation = candidate["rotation_candidate_degrees"]
        self.transform = candidate["candidate_transform_live_to_reference"]
        self.transform_shift = candidate.get("relative_shift_candidate_mm")
        self.map_identity = map_identity
        self.status = "pruefung_laeuft"
        self.reason = None

    def check_map(self, candidate, run_generation, map_identity=None):
        if not self.active:
            return
        if run_generation != self.run_generation:
            self.invalidate("reinigungsvorgang_oder_kartenreset")
            return
        if (self.map_identity is not None and map_identity is not None
                and self.map_identity != map_identity):
            self.invalidate("kartenkennung_gewechselt")
            return
        if not candidate_is_usable(candidate):
            self.invalidate("kartenabgleich_nicht_mehr_eindeutig")
            return
        if candidate["rotation_candidate_degrees"] != self.rotation:
            self.invalidate("kartendrehung_gewechselt")
            return
        if math.dist(
            candidate.get("relative_shift_candidate_mm", (0,0)),
            self.transform_shift or (0,0)
        ) > 150:
            self.invalidate("kartenversatz_gewechselt")
            return

    def snapshot(self, name, position, event_time, source_time, now=None):
        """Two separate fresh sensor reports, >=8s apart, <=120mm drift."""
        if not position:
            raise ValueError("Keine Xiaomi-Roboterposition")
        now = now or datetime.now(timezone.utc)
        if event_time is None:
            raise ValueError("Quellzeitstempel fehlt")
        if isinstance(event_time, str):
            event_time = datetime.fromisoformat(event_time)
        if event_time.tzinfo is None:
            raise ValueError("Positionszeit ohne Zeitzone")
        age = (now - event_time).total_seconds()
        if not -5 <= age <= MAX_SOURCE_AGE_S:
            raise ValueError("Positionsmeldung zu alt oder Uhrzeiten stimmen nicht")
        position = {"x": int(position["x"]), "y": int(position["y"])}
        previous = self.pending.get(name)
        if previous is None:
            self.pending[name] = {
                "position": position,
                "first_time": now,
                "source_time": event_time,
            }
            return None
        elapsed = (now - previous["first_time"]).total_seconds()
        if elapsed < MIN_SAMPLE_SEPARATION_S:
            raise ValueError("Zweite Messung erst nach mindestens 8 Sekunden")
        if event_time <= previous["source_time"]:
            raise ValueError("Noch kein neuer Positionsbericht vom Map Extractor")
        drift = math.dist(
            (position["x"], position["y"]),
            (previous["position"]["x"], previous["position"]["y"])
        )
        if drift > MAX_STATIONARY_DRIFT_MM:
            self.pending[name] = {
                "position": position,
                "first_time": now,
                "source_time": event_time,
            }
            raise ValueError(
                f"Roberto hat sich zwischen den Messungen um {drift:.0f} mm bewegt"
            )
        self.pending.pop(name, None)
        return {
            "position": position,
            "drift_mm": round(drift),
            "time": now.isoformat(),
            "source": source_time,
        }

    def store_reference_point(self, name, stable):
        if not self.baseline_enabled:
            raise ValueError(
                "Referenzphase nicht aktiv. Vollständige Karte mit capture_reference speichern"
            )
        if name in self.reference_points:
            raise ValueError("Referenzpunkt bereits gespeichert")
        self.reference_points[name] = {
            "name": name,
            **stable["position"],
        }
        self.status = "referenzpunkte_erfassen"
        return len(self.reference_points)

    def verify_point(self, name, stable):
        if not self.active:
            raise ValueError("Prüfung ist nicht gestartet oder wurde gesperrt")
        if name not in self.reference_points:
            raise ValueError("Unbekannter Referenzpunkt")
        if name in self.results:
            raise ValueError("Dieser Prüfpunkt wurde bereits abgeschlossen")
        projected = projected_reference_point(stable["position"], self.transform)
        target = self.reference_points[name]
        deviation = math.dist(
            (projected["x"], projected["y"]),
            (target["x"], target["y"])
        )
        result = {
            "name": name,
            "deviation_mm": round(deviation),
            "passed": deviation <= MAX_RESIDUAL_MM,
            "live_x": stable["position"]["x"],
            "live_y": stable["position"]["y"],
            "projected_reference_x": round(projected["x"]),
            "projected_reference_y": round(projected["y"]),
            "reference_x": target["x"],
            "reference_y": target["y"],
            "stationary_drift_mm": stable["drift_mm"],
            "confirmed_by_operator": True,
        }
        self.results[name] = result
        if not result["passed"]:
            self.active = False
            self.status = "gesperrt"
            self.reason = f"Prüfpunkt {name}: Abweichung {deviation:.0f} mm"
        elif len(self.results) >= REQUIRED_POINTS:
            if all(x["passed"] for x in self.results.values()):
                self.status = "pruefpunkte_bestanden"
        return result

    def info(self):
        return {
            "status": self.status,
            "reason": self.reason,
            "reference_points": len(self.reference_points),
            "reference_point_names": sorted(self.reference_points),
            "checked_points": len(self.results),
            "pending_name": next(iter(self.pending), None),
            "checks": list(self.results.values()),
            "rotation_degrees": self.rotation,
            "map_identity": self.map_identity,
            "reference_hash": self.reference_hash,
            "coordinates_tested_by_operator": self.status == "pruefpunkte_bestanden",
            "automatic_navigation_enabled": False,
            "no_go_zones_enforced": False,
        }
