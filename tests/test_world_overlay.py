"""Offline tests; no Home Assistant / Xiaomi token required."""
import importlib.util
import io
import json
import pathlib
import unittest

from PIL import Image, ImageDraw

SOURCE = (
    pathlib.Path(__file__).resolve().parents[1]
    / "custom_components" / "roberto_zones" / "world_overlay.py"
)
spec = importlib.util.spec_from_file_location("roberto_world_overlay", SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

CAL = [
    {"map": {"x": 10, "y": 10}, "vacuum": {"x": 25500, "y": 25500}},
    {"map": {"x": 110, "y": 10}, "vacuum": {"x": 30500, "y": 25500}},
    {"map": {"x": 10, "y": 110}, "vacuum": {"x": 25500, "y": 20500}},
]


def synthetic_map():
    im = Image.new("RGBA", (160, 140), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)
    draw.rectangle((20, 20, 130, 110), fill=(130, 200, 220, 255))
    draw.rectangle((48, 45, 65, 62), fill=(0, 0, 0, 0))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


class OverlayTests(unittest.TestCase):
    def test_parse_v3_sensor_state(self):
        self.assertEqual(
            module.parse_position(json.dumps({"x": 25485, "y": 25900, "a": 45}))["x"],
            25485,
        )
        self.assertIsNone(module.parse_position("unknown"))
        self.assertIsNone(module.parse_position("null"))

    def test_calibration_is_invertible(self):
        matrix = module.calibration_matrix(CAL)
        self.assertIsNotNone(matrix)
        self.assertAlmostEqual(matrix[0, 0], 50, places=3)
        self.assertAlmostEqual(matrix[1, 1], -50, places=3)
        self.assertIsNone(module.calibration_matrix(CAL[:2]))

    def test_uncalibrated_screenshot_fails_closed(self):
        src = synthetic_map()
        png, info = module.build_overlay(
            src, src, None, CAL, {"x": 25500, "y": 25500}
        )
        self.assertTrue(png.startswith(b"\x89PNG"))
        self.assertEqual(info["overlay_mode"], "side_by_side_not_registered")
        self.assertFalse(info["navigation_coordinates_verified"])

    def test_world_calibrated_map_is_only_candidate(self):
        src = synthetic_map()
        png, info = module.build_overlay(
            src, src, CAL, CAL, {"x": 25500, "y": 25500},
            {"x": 25500, "y": 25500}
        )
        self.assertTrue(png.startswith(b"\x89PNG"))
        self.assertEqual(info["overlay_mode"], "world_calibrated_preview")
        self.assertGreater(info["floor_overlap_ratio"], 0.95)
        self.assertTrue(info["visual_alignment_candidate"])
        self.assertFalse(info["navigation_coordinates_verified"])
        self.assertFalse(info["can_send_automatic_targets"])

    def test_incompatible_map_alignment_rejected(self):
        src = synthetic_map()
        shifted = [
            {"map": p["map"], "vacuum": {
                "x": p["vacuum"]["x"] + 10000,
                "y": p["vacuum"]["y"]
            }} for p in CAL
        ]
        _, info = module.build_overlay(src, src, CAL, shifted)
        self.assertFalse(info["visual_alignment_candidate"])
        self.assertFalse(info["navigation_coordinates_verified"])


if __name__ == "__main__":
    unittest.main()
