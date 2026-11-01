"""Offline regression checks: geometry pixels must be independent of robot paths."""
from __future__ import annotations

import importlib.util
import io
import pathlib
import unittest
from types import SimpleNamespace

from PIL import Image, ImageDraw
from vacuum_map_parser_base.map_data import Point

ROOT = pathlib.Path(__file__).resolve().parents[1]
FILE = ROOT / "custom_components" / "roberto_zones" / "native_geometry.py"
spec = importlib.util.spec_from_file_location("roberto_native_geometry", FILE)
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)

CAL = [
    {"vacuum": {"x": 25500, "y": 25500}, "map": {"x": 120, "y": 120}},
    {"vacuum": {"x": 30500, "y": 25500}, "map": {"x": 220, "y": 120}},
    {"vacuum": {"x": 25500, "y": 30500}, "map": {"x": 120, "y": 20}},
]


class FakeDimensions:
    def to_img(self, point):
        return Point(
            120 + (point.x - 25500) / 50,
            120 - (point.y - 25500) / 50,
        )


def native_floor():
    img = Image.new("RGBA", (240, 240), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle((40, 30, 160, 110), fill=(100, 196, 254, 255))
    draw.rectangle((130, 90, 160, 202), fill=(100, 196, 254, 255))
    draw.rectangle((152, 173, 213, 202), fill=(100, 196, 254, 255))
    return img


def map_data_from_native(img):
    return SimpleNamespace(image=SimpleNamespace(
        data=img, is_empty=False, dimensions=FakeDimensions()
    ))


def rendered_with_path(base, path_variant):
    """Simulate a renderer that paints paths/robot markers AFTER geometry."""
    img = base.copy()
    draw = ImageDraw.Draw(img)
    if path_variant == 1:
        draw.line((45, 50, 120, 100, 140, 181, 180, 195), fill="#83c2e2", width=5)
        draw.ellipse((130, 164, 148, 182), fill="#ffd36a")
    if path_variant == 2:
        draw.line((45, 86, 110, 46, 148, 130, 207, 189), fill="#83c2e2", width=5)
        draw.ellipse((195, 179, 215, 199), fill="#ffd36a")
    output = io.BytesIO()
    img.save(output, format="PNG")
    return output.getvalue()


class NativeGeometryTests(unittest.TestCase):
    def test_geometry_is_not_rendered_path(self):
        native_image = native_floor()
        cache = map_data_from_native(native_image)
        source_a = rendered_with_path(native_image, 1)
        source_b = rendered_with_path(native_image, 2)
        self.assertNotEqual(source_a, source_b)

        geometry_a, calibration_a, meta_a = native.extract_native_geometry(cache, CAL)
        geometry_b, calibration_b, meta_b = native.extract_native_geometry(cache, CAL)

        self.assertEqual(geometry_a, geometry_b)
        self.assertEqual(meta_a["geometry_sha256"], meta_b["geometry_sha256"])
        self.assertEqual(calibration_a, calibration_b)
        self.assertFalse(meta_a["tracks_included"])
        self.assertFalse(meta_a["robot_marker_included"])
        self.assertAlmostEqual(calibration_a[0]["map"]["x"], 120)
        self.assertAlmostEqual(calibration_a[1]["map"]["x"], 220)
        self.assertAlmostEqual(calibration_a[2]["map"]["y"], 20)

    def test_parser_incompatible_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "native Kartenebene"):
            native.extract_native_geometry(SimpleNamespace(image=None), CAL)
        with self.assertRaisesRegex(ValueError, "native Geometrieebene"):
            native.extract_native_geometry(
                SimpleNamespace(image=SimpleNamespace(
                    data=b"wrong", dimensions=FakeDimensions(),
                    is_empty=False,
                )), CAL,
            )

    def test_too_large_image_is_rejected(self):
        large_image = Image.new("RGBA", (1400, 40))
        with self.assertRaisesRegex(ValueError, "Kartengroesse"):
            native.extract_native_geometry(
                map_data_from_native(large_image), CAL
            )


if __name__ == "__main__":
    unittest.main()
