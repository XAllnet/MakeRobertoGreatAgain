"""Regression tests for path-free geometry extracted from RAW Roborock IMAGE blocks."""
from __future__ import annotations

import gzip
import importlib.util
import io
import pathlib
import struct
import unittest
from types import SimpleNamespace

import numpy as np
from PIL import Image, ImageDraw

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
    width = height = 240
    top = left = 0
    scale = 1
    rotation = 0

    def to_img(self, point):
        from vacuum_map_parser_base.map_data import Point
        return Point(
            120 + (point.x - 25500) / 50,
            120 - (point.y - 25500) / 50,
        )


def cached_data(decorated_image=None):
    if decorated_image is None:
        decorated_image = Image.new("RGBA", (240, 240), "black")
    return SimpleNamespace(image=SimpleNamespace(
        data=decorated_image, is_empty=False, dimensions=FakeDimensions()
    ))


def image_cells():
    """Underlying map image: wall occupied=1, free/scanned=255 or 7."""
    raw = np.zeros((240, 240), dtype=np.uint8)
    raw[30:210, 30] = 1
    raw[30:210, 210] = 1
    raw[30, 30:211] = 1
    raw[209, 30:211] = 1
    raw[40:209, 40:210] = 255
    raw[55:180, 60:185] = 7
    # Reinstate walls after filling free cells.
    raw[30:210, 30] = 1
    raw[30:210, 210] = 1
    raw[30, 30:211] = 1
    raw[209, 30:211] = 1
    return raw


def block(kind, payload, extra_header=b""):
    return struct.pack("<HHI", kind, 8 + len(extra_header), len(payload)) + extra_header + payload


def source_map(raw_cells, path):
    hdr = bytearray(20)
    struct.pack_into("<H", hdr, 2, 20)
    img_data = block(
        2, raw_cells.tobytes(),
        struct.pack("<iiii", 0, 0, 240, 240),
    )
    # The path belongs to a separate Roborock type-3 block.
    path_data = block(3, path)
    return gzip.compress(bytes(hdr) + img_data + path_data)


def decorated_with_track(route):
    image = Image.new("RGBA", (240, 240), "black")
    pen = ImageDraw.Draw(image)
    pen.line(route, fill="cyan", width=5)
    pen.ellipse((100, 100, 130, 130), fill="orange")
    return image


class RawGeometryTests(unittest.TestCase):
    def test_different_rendered_paths_and_path_blocks_same_geometry(self):
        raw_cells = image_cells()
        first = source_map(raw_cells, b"walk-one" * 20)
        second = source_map(raw_cells, b"walk-two" * 20)
        self.assertNotEqual(first, second)
        a = native.extract_native_geometry(first, cached_data(
            decorated_with_track((35, 35, 190, 205))), CAL)
        b = native.extract_native_geometry(second, cached_data(
            decorated_with_track((190, 35, 35, 205))), CAL)
        self.assertEqual(a[0], b[0])
        self.assertEqual(a[1], b[1])
        self.assertEqual(a[2]["geometry_sha256"], b[2]["geometry_sha256"])
        self.assertFalse(a[2]["tracks_included"])
        self.assertFalse(a[2]["scan_floor_included"])
        self.assertEqual(a[2]["geometry_source"], "cached_roborock_raw_image_block")

        with Image.open(io.BytesIO(a[0])) as img:
            rgba = np.asarray(img.convert("RGBA"))
            self.assertEqual(rgba[30, 30, 3], 255)  # walls
            self.assertEqual(rgba[80, 80, 3], 0)  # map floor/scan excluded
            self.assertEqual(rgba[120, 120, 3], 0)  # robot/path excluded

    def test_geometry_change_changes_sha(self):
        baseline = image_cells()
        modified = baseline.copy()
        modified[70:100, 100] = 1
        first = native.extract_native_geometry(
            source_map(baseline, b"track"), cached_data(), CAL
        )[2]["geometry_sha256"]
        second = native.extract_native_geometry(
            source_map(modified, b"track"), cached_data(), CAL
        )[2]["geometry_sha256"]
        self.assertNotEqual(first, second)

    def test_bad_compressed_map_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "Gzip"):
            native.extract_native_geometry(
                b"not-a-gzip-map" * 5, cached_data(), CAL
            )

    def test_map_without_image_block_rejected(self):
        header = bytearray(20)
        struct.pack_into("<H", header, 2, 20)
        with self.assertRaisesRegex(ValueError, "IMAGE-Block fehlt"):
            native.extract_native_geometry(
                gzip.compress(bytes(header) + block(3, b"track")),
                cached_data(), CAL,
            )

    def test_unsupported_native_dimensions_rejected(self):
        broken = cached_data()
        broken.image.dimensions.width = -5
        with self.assertRaisesRegex(ValueError, "passt nicht"):
            native.extract_native_geometry(
                source_map(image_cells(), b"route"), broken, CAL
            )


if __name__ == "__main__":
    unittest.main()
