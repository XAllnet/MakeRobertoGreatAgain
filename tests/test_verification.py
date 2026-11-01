"""Pure offline tests for explicitly confirmed physical calibration."""
from datetime import datetime, timedelta, timezone
import importlib.util
import pathlib
import unittest

path = (
    pathlib.Path(__file__).resolve().parents[1] /
    "custom_components" / "roberto_zones" / "verification.py"
)
spec = importlib.util.spec_from_file_location("roberto_verification", path)
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)

BASE = {
    "a": {"name": "a", "x": 24500, "y": 24500},
    "b": {"name": "b", "x": 28000, "y": 24500},
    "c": {"name": "c", "x": 24500, "y": 28000},
}

TRANSFORM = [
    [0., -1., 51000.],
    [1., 0., 0.],
    [0., 0., 1.],
]
CANDIDATE = {
    "overlay_mode": "rotation_corrected_diagnostic",
    "visual_alignment_candidate": True,
    "anchor_assumed": False,
    "reference_calibrated": True,
    "live_calibrated": True,
    "rotation_candidate_degrees": 90,
    "relative_shift_candidate_mm": [0,0],
    "candidate_transform_live_to_reference": TRANSFORM,
}


class CheckpointsTest(unittest.TestCase):
    def test_non_collinear_spread(self):
        self.assertTrue(v.reference_spread_ok(BASE.values()))
        self.assertFalse(v.reference_spread_ok([
            {"x": 0, "y": 0}, {"x": 1500, "y": 0}, {"x": 3000, "y": 0},
        ]))

    def test_90_degree_transform(self):
        p = v.projected_reference_point({"x": 24500, "y": 26500}, TRANSFORM)
        self.assertAlmostEqual(p["x"], 24500)
        self.assertAlmostEqual(p["y"], 24500)

    def test_candidate_fails_closed_without_dock(self):
        bad = dict(CANDIDATE)
        bad["anchor_assumed"] = True
        self.assertFalse(v.candidate_is_usable(bad))

    def test_reference_baseline_and_restart_in_memory(self):
        sess = v.CheckpointSession()
        sess.initialize_reference("abc")
        self.assertTrue(sess.baseline_enabled)
        stable = {"position": {"x": 24500, "y": 24500}}
        self.assertEqual(sess.store_reference_point("a", stable), 1)
        sess.invalidate("new map")
        self.assertFalse(sess.baseline_enabled)
        self.assertEqual(len(sess.reference_points), 1)

    def test_same_reference_session_cannot_be_verified(self):
        sess = v.CheckpointSession()
        sess.initialize_reference("sha")
        sess.reference_points = dict(BASE)
        with self.assertRaisesRegex(ValueError, "Referenzaufnahme noch aktiv"):
            sess.begin(CANDIDATE, run_generation=0)

    def test_begin_requires_valid_reference_and_map(self):
        sess = v.CheckpointSession()
        sess.reference_points = dict(BASE)
        sess.begin(CANDIDATE, run_generation=4, map_identity="map:1")
        self.assertTrue(sess.active)
        self.assertEqual(sess.rotation, 90)
        sess.check_map(CANDIDATE, run_generation=5, map_identity="map:1")
        self.assertFalse(sess.active)
        self.assertEqual(sess.status, "gesperrt")

    def test_rotation_change_invalidates(self):
        sess = v.CheckpointSession()
        sess.reference_points = dict(BASE)
        sess.begin(CANDIDATE, 3)
        altered = dict(CANDIDATE)
        altered["rotation_candidate_degrees"] = 180
        sess.check_map(altered, 3)
        self.assertFalse(sess.active)

    def test_sample_requires_two_new_fresh_reports(self):
        sess = v.CheckpointSession()
        now = datetime.now(timezone.utc)
        position = {"x": 24500, "y": 26500}
        first = sess.snapshot("a", position, now-timedelta(seconds=1), "sensor", now)
        self.assertIsNone(first)
        with self.assertRaisesRegex(ValueError, "mindestens 8"):
            sess.snapshot("a", position, now+timedelta(seconds=2), "sensor", now+timedelta(seconds=3))
        with self.assertRaisesRegex(ValueError, "neuer Positionsbericht"):
            sess.snapshot("a", position, now-timedelta(seconds=1), "sensor", now+timedelta(seconds=12))
        second = sess.snapshot(
            "a", {"x": 24506, "y": 26497},
            now+timedelta(seconds=11), "sensor", now+timedelta(seconds=12)
        )
        self.assertIsNotNone(second)
        self.assertLess(second["drift_mm"], 10)

    def test_old_report_fails(self):
        sess = v.CheckpointSession()
        now = datetime.now(timezone.utc)
        with self.assertRaisesRegex(ValueError, "zu alt"):
            sess.snapshot("a", {"x": 25000, "y": 25000},
                          now-timedelta(seconds=180), "sensor", now)

    def test_3_manual_landmarks_verify_without_drive_commands(self):
        sess = v.CheckpointSession()
        sess.reference_points = dict(BASE)
        sess.begin(CANDIDATE, 2)
        # Inverse 90-degree coordinate transform: live x=ref y; live y=51000-ref x.
        for key, point in BASE.items():
            observed = {"position": {
                "x": point["y"] + 25,
                "y": 51000 - point["x"] - 30,
            }, "drift_mm": 8}
            result = sess.verify_point(key, observed)
            self.assertTrue(result["passed"])
            self.assertLess(result["deviation_mm"], 60)
        self.assertEqual(sess.status, "pruefpunkte_bestanden")
        self.assertFalse(sess.info()["automatic_navigation_enabled"])

    def test_failed_checkpoint_locks_out(self):
        sess = v.CheckpointSession()
        sess.reference_points = dict(BASE)
        sess.begin(CANDIDATE, 2)
        bad = {"position": {"x": 15000, "y": 13000}, "drift_mm": 0}
        result = sess.verify_point("a", bad)
        self.assertFalse(result["passed"])
        self.assertFalse(sess.active)
        self.assertEqual(sess.status, "gesperrt")


if __name__ == "__main__":
    unittest.main()
