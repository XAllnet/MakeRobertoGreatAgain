"""Conservative, time-separated visual-only registration consensus.

Three distinct map-mask observations must agree. Never authorizes movement.
"""
from __future__ import annotations

import math


class RegistrationConsensus:
    """Event-driven consensus that rejects changing or ambiguous candidates."""

    REQUIRED = 3
    MAX_SHIFT_CHANGE_MM = 120

    def __init__(self):
        self.reset("noch_keine_kartenanalyse")

    def reset(self, reason):
        self.rotation = None
        self.shift = None
        self.count = 0
        self.last_fingerprint = None
        self.reason = reason
        self.confirmed = False

    def observe(self, data):
        """Return True only after three DIFFERENT, agreeing source masks."""
        if (not isinstance(data, dict)
                or data.get("visual_alignment_candidate") is not True
                or data.get("anchor_assumed") is not False
                or not isinstance(data.get("rotation_candidate_degrees"), int)
                or not isinstance(data.get("relative_shift_candidate_mm"), list)
                or len(data["relative_shift_candidate_mm"]) != 2):
            self.reset("ausrichtung_oder_dock_unklar")
            return False
        fingerprint = data.get("live_mask_fingerprint")
        if not isinstance(fingerprint, str) or not fingerprint:
            self.reset("karten_fingerprint_fehlt")
            return False
        rotation = data["rotation_candidate_degrees"]
        shift = [int(x) for x in data["relative_shift_candidate_mm"]]
        if not all(math.isfinite(x) for x in shift):
            self.reset("kartenversatz_ungueltig")
            return False
        if self.last_fingerprint == fingerprint:
            # Re-evaluation of the same pixels is not independent evidence.
            return self.confirmed
        stable_against_previous = (
            self.rotation == rotation
            and self.shift is not None
            and math.dist(self.shift, shift) <= self.MAX_SHIFT_CHANGE_MM
        )
        if not stable_against_previous:
            self.rotation = rotation
            self.shift = shift
            self.count = 1
            self.confirmed = False
            self.reason = "neuer_kandidat"
        else:
            self.count += 1
            self.shift = shift
            self.confirmed = self.count >= self.REQUIRED
            self.reason = "visuell_stabil" if self.confirmed else "weitere_kartenupdates_noetig"
        self.last_fingerprint = fingerprint
        return self.confirmed

    def can_preview(self):
        if not self.confirmed:
            return None
        return {"rotation_degrees": self.rotation, "shift_mm": list(self.shift)}

    def info(self):
        return {
            "consecutive_distinct_map_observations": self.count,
            "required_observations": self.REQUIRED,
            "temporal_visual_match": self.confirmed,
            "reason": self.reason,
            "navigation_coordinates_verified": False,
            "automatic_navigation_enabled": False,
        }
