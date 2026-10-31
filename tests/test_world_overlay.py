"""Read-only registration regression tests; no Home Assistant required."""
import importlib.util
import io
import json
import pathlib
import sys
import types
import unittest

from PIL import Image, ImageDraw

ROOT = pathlib.Path(__file__).resolve().parents[1]
COMP = ROOT / "custom_components" / "roberto_zones"
PKG = "roberto_overlay_test_package"
package = types.ModuleType(PKG)
package.__path__ = [str(COMP)]
sys.modules[PKG] = package
spec = importlib.util.spec_from_file_location(
    f"{PKG}.world_overlay", COMP / "world_overlay.py"
)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

CAL = [
    {"map": {"x": 120, "y": 120}, "vacuum": {"x": 25500, "y": 25500}},
    {"map": {"x": 220, "y": 120}, "vacuum": {"x": 30500, "y": 25500}},
    {"map": {"x": 120, "y": 220}, "vacuum": {"x": 25500, "y": 20500}},
]
DOCK = {"x": 25500, "y": 25500}


def asymmetric_image():
    im = Image.new("RGBA", (240, 240), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)
    draw.rectangle((42, 35, 145, 102), fill=(130, 200, 220, 255))
    draw.rectangle((105, 101, 132, 186), fill=(130, 200, 220, 255))
    draw.rectangle((128, 155, 218, 185), fill=(130, 200, 220, 255))
    draw.rectangle((72, 48, 87, 75), fill=(0, 0, 0, 0))
    draw.rectangle((152, 166, 164, 177), fill=(0, 0, 0, 0))
    return im


def png(im):
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


class RegistrationTests(unittest.TestCase):
    def test_parse_v3_sensor(self):
        pos = module.parse_position(json.dumps({"x": 25485, "y": 25900, "a": 45}))
        self.assertEqual(pos["x"], 25485)
        self.assertIsNone(module.parse_position("unknown"))
        self.assertIsNone(module.parse_position("null"))

    def test_invertible_calibration(self):
        matrix = module.calibration_matrix(CAL)
        self.assertAlmostEqual(matrix[0, 0], 50, places=3)
        self.assertAlmostEqual(matrix[1, 1], -50, places=3)
        self.assertIsNone(module.calibration_matrix(CAL[:2]))

    def test_uncalibrated_reference_kept_separate(self):
        data = png(asymmetric_image())
        rendered, result = module.build_overlay(
            data, data, None, CAL, DOCK
        )
        self.assertTrue(rendered.startswith(b"\x89PNG"))
        self.assertEqual(result["overlay_mode"], "side_by_side_not_registered")
        self.assertFalse(result["navigation_coordinates_verified"])

    def test_same_map_not_position_verified(self):
        data = png(asymmetric_image())
        rendered, result = module.build_overlay(
            data, data, CAL, CAL, DOCK, DOCK, DOCK
        )
        self.assertTrue(rendered.startswith(b"\x89PNG"))
        self.assertEqual(result["overlay_mode"], "rotation_corrected_diagnostic")
        self.assertEqual(result["rotation_candidate_degrees"], 0)
        self.assertGreater(result["rotation_score"], 0.95)
        self.assertFalse(result["navigation_coordinates_verified"])
        self.assertFalse(result["can_send_automatic_targets"])

    def test_rotated_live_map_alignment(self):
        reference = asymmetric_image()
        live = reference.rotate(
            90, Image.Resampling.NEAREST, center=(120, 120), expand=False
        )
        _, result = module.build_overlay(
            png(reference), png(live), CAL, CAL, DOCK, DOCK, DOCK
        )
        self.assertEqual(result["overlay_mode"], "rotation_corrected_diagnostic")
        self.assertIn(result["rotation_candidate_degrees"], (90, 270))
        self.assertGreater(result["rotation_score"], 0.8)
        self.assertFalse(result["navigation_coordinates_verified"])

    def test_shifted_calibration_not_trusted(self):
        ref = png(asymmetric_image())
        shifted = [{
            "map": p["map"],
            "vacuum": {
                "x": p["vacuum"]["x"] + 10000,
                "y": p["vacuum"]["y"],
            },
        } for p in CAL]
        _, result = module.build_overlay(ref, ref, CAL, shifted, DOCK, DOCK, DOCK)
        self.assertFalse(result.get("visual_alignment_candidate", False))
        self.assertFalse(result["navigation_coordinates_verified"])

    def test_missing_dock_never_approved(self):
        data = png(asymmetric_image())
        _, result = module.build_overlay(data, data, CAL, CAL, DOCK)
        self.assertTrue(result["anchor_assumed"])
        self.assertFalse(result["navigation_coordinates_verified"])


if __name__ == "__main__":
    unittest.main()
