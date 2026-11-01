"""Read the existing v3 Map Extractor cached *native* geometry without re-polling.

Map Extractor alpha-24 uses vacuum_map_parser_base.MapData.image.data:
a PIL raster created from native wall/floor cells BEFORE the renderer draws
robot tracks, markers, goto targets, or other transient overlays.

This is a best-effort versioned adapter to an INTERNAL third-party API.
On any unexpected shape, fail closed; never substitute the rendered image.
"""
from __future__ import annotations

import hashlib
from io import BytesIO

from PIL import Image


MAX_NATIVE_IMAGE_PIXELS = 16_000_000
MAX_NATIVE_SIDE = 1200


def extract_native_geometry(map_data, image_calibration):
    """Return (PNG, calibration, diagnostics), or raise ValueError.

    The native geometry PNG intentionally has its own pixel coordinates,
    so its calibration MUST be derived from the native image dimensions.
    """
    if not isinstance(image_calibration, list) or not 3 <= len(image_calibration) <= 12:
        raise ValueError("Keine gueltige Kartenkalibrierung")
    image_data = getattr(map_data, "image", None)
    if image_data is None or getattr(image_data, "is_empty", False):
        raise ValueError("Keine native Kartenebene vorhanden")
    pixels = getattr(image_data, "data", None)
    dimensions = getattr(image_data, "dimensions", None)
    if not isinstance(pixels, Image.Image) or dimensions is None:
        raise ValueError("Map Extractor unterstuetzt keine native Geometrieebene")
    if not hasattr(dimensions, "to_img"):
        raise ValueError("Native Pixelkoordinaten nicht vorhanden")
    width, height = pixels.size
    if (width < 15 or height < 15 or
            width > MAX_NATIVE_SIDE or height > MAX_NATIVE_SIDE or
            width * height > MAX_NATIVE_IMAGE_PIXELS):
        raise ValueError("Unplausible oder zu grosse native Kartengroesse")

    # This parser package is already installed by Xiaomi Cloud Map Extractor.
    # Do not introduce a second parser or fetch the map from the cloud.
    try:
        from vacuum_map_parser_base.map_data import Point
    except ImportError as exc:
        raise ValueError("Map-Parser-Bibliothek nicht verfuegbar") from exc

    native_calibration = []
    try:
        for entry in image_calibration:
            vacuum = entry["vacuum"]
            world_x, world_y = float(vacuum["x"]), float(vacuum["y"])
            mapped = Point(world_x, world_y).to_img(dimensions)
            if not all(map(__import__("math").isfinite, (mapped.x, mapped.y))):
                raise ValueError("Unplausibler Geometrie-Kalibrierungspunkt")
            native_calibration.append({
                "vacuum": {"x": world_x, "y": world_y},
                "map": {"x": float(mapped.x), "y": float(mapped.y)},
            })
    except (KeyError, TypeError, AttributeError, OverflowError) as exc:
        raise ValueError("Native Geometrie-Kalibrierung fehlgeschlagen") from exc

    # Map data is immutable per coordinator update, but copy before encoding
    # because another update can replace the cached MapData.
    raw = BytesIO()
    pixels.convert("RGBA").save(raw, format="PNG", optimize=True)
    png_bytes = raw.getvalue()
    return png_bytes, native_calibration, {
        "geometry_source": "shared_map_extractor_native_cache",
        "tracks_included": False,
        "robot_marker_included": False,
        "geometry_sha256": hashlib.sha256(png_bytes).hexdigest(),
        "geometry_dimensions": [width, height],
        "parser_api": "vacuum_map_parser_base.ImageData.data",
        "navigation_coordinates_verified": False,
    }
