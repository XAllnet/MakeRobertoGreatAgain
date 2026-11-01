"""Regression tests: ambiguous and changing maps must never look verified."""
import importlib.util
from pathlib import Path
import unittest

SOURCE = (
    Path(__file__).resolve().parents[1] /
    "custom_components" / "roberto_zones" / "registration_consensus.py"
)
spec = importlib.util.spec_from_file_location("roberto_consensus", SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def candidate(fingerprint, rotation=90, shift=None):
    return {
        "overlay_mode": "rotation_corrected_diagnostic",
        "visual_alignment_candidate": True,
        "anchor_assumed": False,
        "rotation_candidate_degrees": rotation,
        "relative_shift_candidate_mm": shift or [0, 0],
        "live_mask_fingerprint": fingerprint,
    }


class ConsensusTests(unittest.TestCase):
    def test_requires_three_different_images(self):
        gate = module.RegistrationConsensus()
        self.assertFalse(gate.observe(candidate("frame-A")))
        self.assertFalse(gate.observe(candidate("frame-A")))
        self.assertEqual(gate.info()["consecutive_distinct_map_observations"], 1)
        self.assertFalse(gate.observe(candidate("frame-B")))
        self.assertTrue(gate.observe(candidate("frame-C")))
        self.assertTrue(gate.info()["temporal_visual_match"])
        self.assertEqual(gate.can_preview()["rotation_degrees"], 90)

    def test_alternating_rotation_never_stable(self):
        gate = module.RegistrationConsensus()
        for i, r in enumerate((0, 90, 0, 90, 0, 90)):
            self.assertFalse(gate.observe(candidate(f"frame-{i}", rotation=r)))
            self.assertIsNone(gate.can_preview())

    def test_bad_low_confidence_observation_resets(self):
        gate = module.RegistrationConsensus()
        for i in range(3):
            gate.observe(candidate(str(i)))
        self.assertTrue(gate.confirmed)
        weak = candidate("fourth")
        weak["visual_alignment_candidate"] = False
        self.assertFalse(gate.observe(weak))
        self.assertFalse(gate.confirmed)
        self.assertEqual(gate.count, 0)

    def test_unknown_dock_never_confirms(self):
        gate = module.RegistrationConsensus()
        for i in range(5):
            p = candidate(str(i))
            p["anchor_assumed"] = True
            self.assertFalse(gate.observe(p))

    def test_significant_offset_change_resets(self):
        gate = module.RegistrationConsensus()
        self.assertFalse(gate.observe(candidate("1", shift=[0, 0])))
        self.assertFalse(gate.observe(candidate("2", shift=[50, 0])))
        self.assertFalse(gate.observe(candidate("3", shift=[250, 0])))
        self.assertEqual(gate.count, 1)
        self.assertIsNone(gate.can_preview())

    def test_reset_clears_previous_preview(self):
        gate = module.RegistrationConsensus()
        for i in range(3):
            gate.observe(candidate(str(i)))
        self.assertTrue(gate.confirmed)
        gate.reset("kartenwechsel")
        self.assertFalse(gate.confirmed)
        self.assertIsNone(gate.can_preview())


if __name__ == "__main__":
    unittest.main()
