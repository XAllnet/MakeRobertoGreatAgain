"""Path-free structural geometry from the existing cached Roborock IMAGE block.

IMPORTANT: MapData.image.data is NOT a clean geometry layer! In the v3
Map Extractor it is mutated by ImageGenerator.draw_map(...) to paint paths,
robot markers and other overlays. We must decode the raw IMAGE block from
the ALREADY-CACHED map_data_raw instead. No vacuum or cloud calls.

Supported source: Roborock GZip map format (rockrobo.vacuum.v1).
Unknown formats, missing data or incompatible dimensions fail closed.
"""
from __future__ import annotations

import gzip
import hashlib
import math
import struct
from io import BytesIO

import numpy as np
from PIL import Image

MAX_COMPRESSED_BYTES = 5_000_000
MAX_DECOMPRESSED_BYTES = 9_000_000
MAX_NATIVE_SIDE = 1200
MAX_NATIVE_PIXELS = 1_440_000


def _image_block(raw: bytes):
    """Extract precisely one validated IMAGE block from the decoded map."""
    if len(raw) < 20:
        raise ValueError("Roborock-Kartenheader ist unvollstaendig")
    map_header = struct.unpack_from("<H", raw, 2)[0]
    if map_header < 16 or map_header > 256 or map_header >= len(raw):
        raise ValueError("Roborock-Kartenheader ungueltig")
    position = map_header
    found = None
    blocks = 0
    while position + 8 <= len(raw):
        blocks += 1
        if blocks > 96:
            raise ValueError("Zu viele Roborock-Kartenbloecke")
        kind, header_length = struct.unpack_from("<HH", raw, position)
        data_length = struct.unpack_from("<I", raw, position + 4)[0]
        data_start = position + header_length
        data_end = data_start + data_length
        if (header_length < 8 or header_length > 512
                or data_start > len(raw) or data_end > len(raw)):
            raise ValueError("Roborock-Kartenblock ungueltig")
        if kind == 2:  # RoborockBlockType.IMAGE
            if found is not None or header_length < 24:
                raise ValueError("Mehrdeutiger Roborock-IMAGE-Block")
            top, left, height, width = struct.unpack_from(
                "<iiii", raw, position + header_length - 16
            )
            if (width < 15 or height < 15
                    or width > MAX_NATIVE_SIDE or height > MAX_NATIVE_SIDE
                    or width * height > MAX_NATIVE_PIXELS
                    or data_length != width * height):
                raise ValueError("IMAGE-Pixelmasse ungueltig")
            found = (raw[data_start:data_end], left, top, width, height)
        position = data_end
    if found is None:
        raise ValueError("Roborock-IMAGE-Block fehlt")
    if position != len(raw):
        raise ValueError("Unerwartete Daten am Kartenende")
    return found


def extract_native_geometry(raw_map, map_data, image_calibration):
    """Return geometry PNG, its UNROTATED world calibration, and diagnostics.

    Registration uses structural OCCUPIED wall cells only; path and scan/floor
    cells are discarded, not painted and then heuristically 'erased'.
    """
    if (not isinstance(raw_map, bytes) or
            not (32 <= len(raw_map) <= MAX_COMPRESSED_BYTES) or
            not raw_map.startswith(b"\x1f\x8b")):
        raise ValueError("Keine gueltigen gecachten Roborock-Gzip-Kartendaten")
    if not isinstance(image_calibration, list) or not 3 <= len(image_calibration) <= 12:
        raise ValueError("Kartenkalibrierung fehlt")
    image_data = getattr(map_data, "image", None)
    dimensions = getattr(image_data, "dimensions", None)
    if dimensions is None or getattr(image_data, "is_empty", True):
        raise ValueError("Nativer Kartenrahmen fehlt")

    # Decompress with an explicit size ceiling, even for corrupted inputs.
    try:
        with gzip.GzipFile(fileobj=BytesIO(raw_map)) as stream:
            decoded = stream.read(MAX_DECOMPRESSED_BYTES + 1)
    except (OSError, EOFError, ValueError) as exc:
        raise ValueError("Roborock-Gzip-Karte ist beschaedigt") from exc
    if len(decoded) > MAX_DECOMPRESSED_BYTES:
        raise ValueError("Roborock-Kartenblock ist zu gross")

    data, left, top, full_width, full_height = _image_block(decoded)
    # ImageData dimensions already include any Map Extractor trimming.
    try:
        width, height = int(dimensions.width), int(dimensions.height)
        trim_left = int(dimensions.left) - left
        trim_bottom = int(dimensions.top) - top
        scale = float(dimensions.scale)
    except (TypeError, AttributeError, ValueError) as exc:
        raise ValueError("Native Bildabmessungen fehlen") from exc
    if (width < 15 or height < 15 or
            trim_left < 0 or trim_bottom < 0
            or trim_left + width > full_width
            or trim_bottom + height > full_height
            or not math.isfinite(scale) or scale <= 0 or scale > 4):
        raise ValueError("Roborock-IMAGE-Block passt nicht zur Live-Karte")
    out_width, out_height = round(width * scale), round(height * scale)
    if (out_width > MAX_NATIVE_SIDE or out_height > MAX_NATIVE_SIDE
            or out_width * out_height > MAX_NATIVE_PIXELS):
        raise ValueError("Native Kartenmaske ist zu gross")

    # Roborock image bytes use bottom-to-top Y. Ignore free/scan/room cells
    # (0xFF, 0x07, values with low 3 bits = 7) and isolated robot path blocks.
    # Occupied cells: MAP_WALL(0x01), MAP_WALL_V2(low bits 1),
    # GREY_WALL(low bits 0, except MAP_OUTSIDE 0x00).
    cells = np.frombuffer(data, dtype=np.uint8).reshape(full_height, full_width)
    clipped = cells[
        trim_bottom:trim_bottom + height,
        trim_left:trim_left + width,
    ]
    occupied = (
        (clipped != 0)
        & (clipped != 255)
        & (clipped != 7)
        & (((clipped & 7) == 0) | ((clipped & 7) == 1))
    )
    occupied = np.flipud(occupied)
    wall_pixels = int(np.count_nonzero(occupied))
    if wall_pixels < 80 or wall_pixels > width * height * 0.6:
        raise ValueError(
            "Zu wenig oder unplausibel viele Wandzellen fuer sicheren Abgleich"
        )
    alpha = (occupied.astype(np.uint8) * 255)
    rgba = np.empty((height, width, 4), dtype=np.uint8)
    rgba[:, :, :3] = 255
    rgba[:, :, 3] = alpha
    image = Image.fromarray(rgba, "RGBA")
    if (out_width, out_height) != image.size:
        image = image.resize((out_width, out_height), Image.Resampling.NEAREST)

    try:
        from vacuum_map_parser_base.map_data import Point
    except ImportError as exc:
        raise ValueError("Gemeinsame Map-Parser-Bibliothek fehlt") from exc
    calibration = []
    for entry in image_calibration:
        try:
            v = entry["vacuum"]
            world_x, world_y = float(v["x"]), float(v["y"])
            point = Point(world_x, world_y).to_img(dimensions)
            if not all(map(math.isfinite, (world_x, world_y, point.x, point.y))):
                raise ValueError("Nicht-endliche native Kalibrierung")
            calibration.append({
                "vacuum": {"x": world_x, "y": world_y},
                "map": {"x": float(point.x), "y": float(point.y)},
            })
        except (KeyError, AttributeError, TypeError, OverflowError) as exc:
            raise ValueError("Unvollstaendige native Kalibrierung") from exc

    target = BytesIO()
    image.save(target, format="PNG", optimize=True)
    image_png = target.getvalue()
    return image_png, calibration, {
        "geometry_source": "cached_roborock_raw_image_block",
        "geometry_only": True,
        "tracks_included": False,
        "robot_marker_included": False,
        "scan_floor_included": False,
        "geometry_sha256": hashlib.sha256(image_png).hexdigest(),
        "geometry_dimensions": [out_width, out_height],
        "occupied_wall_pixels": wall_pixels,
        "navigation_coordinates_verified": False,
    }
