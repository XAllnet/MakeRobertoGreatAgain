"""Read-only Xiaomi map overlay based on saved affine calibration pairs.

NEVER infer navigation coordinates from an uncalibrated screenshot.
Everything here is a diagnostic visualization, not a path-planning system.
"""
from __future__ import annotations

import json
import math
from io import BytesIO
from collections.abc import Mapping

import numpy as np
from PIL import Image, ImageDraw, ImageOps

MAX_IMAGE_PIXELS = 16_000_000
MAX_EDGE = 1200


def parse_position(value):
    """Read Xiaomi position from v3 diagnostic sensor state or attributes."""
    if value is None:
        return None
    if isinstance(value, str):
        if not value or value in ("unknown", "unavailable", "None"):
            return None
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return None
    if isinstance(value, Mapping):
        if "position" in value and isinstance(value["position"], Mapping):
            value = value["position"]
        try:
            x, y = float(value["x"]), float(value["y"])
            if math.isfinite(x) and math.isfinite(y) and 0 <= x <= 52000 and 0 <= y <= 52000:
                return {"x": round(x), "y": round(y), "angle": value.get("a", value.get("angle"))}
        except (ValueError, TypeError, KeyError):
            return None
    return None


def calibration_matrix(points):
    """Image pixel coordinates -> Xiaomi world millimeters, affine fit."""
    if not isinstance(points, list) or len(points) < 3 or len(points) > 12:
        return None
    pixels, vacuum = [], []
    try:
        for point in points:
            m, v = point["map"], point["vacuum"]
            p = [float(m["x"]), float(m["y"]), 1.]
            q = [float(v["x"]), float(v["y"])]
            if not all(math.isfinite(t) for t in p + q):
                return None
            pixels.append(p)
            vacuum.append(q)
    except (TypeError, ValueError, KeyError):
        return None
    p, q = np.array(pixels), np.array(vacuum)
    if np.linalg.matrix_rank(p) < 3:
        return None
    coeff, _, _, _ = np.linalg.lstsq(p, q, rcond=None)
    err = np.linalg.norm(p @ coeff - q, axis=1)
    matrix = np.eye(3, dtype=float)
    matrix[:2, :] = coeff.T
    basis = matrix[:2, :2]
    lengths = np.linalg.norm(basis, axis=0)
    if min(lengths) < 3 or max(lengths) > 400:
        return None
    if max(lengths) / min(lengths) > 1.25 or abs(np.linalg.det(basis)) < 30:
        return None
    # The original calibration points are generated from the map renderer;
    # residual 100mm allows tiny rounding while rejecting inconsistent data.
    if float(err.max()) > 100:
        return None
    return matrix


def floor_mask(source):
    with Image.open(BytesIO(source)) as raw:
        if raw.width * raw.height > MAX_IMAGE_PIXELS:
            raise ValueError("Map image is too large")
        image = ImageOps.exif_transpose(raw)
        if max(image.size) > MAX_EDGE:
            # Calibration is expressed in original pixels; do not downsample
            # calibrated maps here. Reject oversized maps instead.
            raise ValueError("Map image exceeds 1200 pixel processing limit")
        rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    rgb = rgba[:, :, :3].astype(np.int16)
    alpha = rgba[:, :, 3]
    if float(np.mean(alpha < 240)) > 0.03:
        mask = alpha >= 100
    else:
        height, width = alpha.shape
        rim = max(2, min(height, width) // 35)
        border = np.concatenate((
            rgb[:rim].reshape(-1, 3),
            rgb[-rim:].reshape(-1, 3),
            rgb[:, :rim].reshape(-1, 3),
            rgb[:, -rim:].reshape(-1, 3)
        ), axis=0)
        background = np.median(border, axis=0)
        mask = np.sum((rgb - background) ** 2, axis=2) >= 65 ** 2
    if not 80 < int(mask.sum()) < mask.size * 0.97:
        raise ValueError("No usable floor silhouette found")
    return mask


def _floor_render(mask, tint):
    img = Image.new("RGB", (mask.shape[1], mask.shape[0]), "#15283a")
    overlay = Image.new("RGB", img.size, tint)
    img.paste(overlay, mask=Image.fromarray((mask * 255).astype("uint8")))
    return img


def _fit_in(image, bounds):
    w, h = image.size
    tw, th = bounds
    factor = min(tw / w, th / h)
    return image.resize(
        (max(1, round(w * factor)), max(1, round(h * factor))),
        Image.Resampling.NEAREST
    )


def _dot(draw, p, color, label=None, radius=7):
    x, y = p
    draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=color, outline="white", width=2)
    if label:
        draw.text((x+12, y-7), label, fill=color)


def build_overlay(reference, live, reference_points=None, live_points=None,
                  robot=None, charger=None):
    """Return PNG and always-conservative diagnostics.

    If historical reference lacks its own image->world calibration, generate
    two *separate* images. Never pretend they share a coordinate frame.
    """
    refmask, livemask = floor_mask(reference), floor_mask(live)
    ref_t, live_t = calibration_matrix(reference_points), calibration_matrix(live_points)
    result = {
        "reference_calibrated": ref_t is not None,
        "live_calibrated": live_t is not None,
        "robot_position_available": robot is not None,
        "charger_position_available": charger is not None,
        "navigation_coordinates_verified": False,
        "can_send_automatic_targets": False,
    }
    if robot:
        result["robot_world_x"] = robot["x"]
        result["robot_world_y"] = robot["y"]
    if charger:
        result["charger_world_x"] = charger["x"]
        result["charger_world_y"] = charger["y"]
        result["charger_near_nominal_origin"] = (
            math.hypot(charger["x"] - 25500, charger["y"] - 25500) <= 800
        )

    if ref_t is None or live_t is None:
        board = Image.new("RGB", (1050, 540), "#0d1b2a")
        pen = ImageDraw.Draw(board)
        pen.text((30, 13), "REFERENZ (historisch)" , fill="#ffffff")
        pen.text((555, 13), "LIVE-KARTE", fill="#ffffff")
        refimg = _fit_in(_floor_render(refmask, "#6b96b3"), (480, 470))
        liveimg = _fit_in(_floor_render(livemask, "#61d2df"), (480, 470))
        board.paste(refimg, (30+(480-refimg.width)//2, 42+(470-refimg.height)//2))
        left = 555+(480-liveimg.width)//2
        top = 42+(470-liveimg.height)//2
        board.paste(liveimg, (left, top))
        if robot and live_t is not None:
            try:
                src = np.linalg.inv(live_t) @ np.array([robot["x"], robot["y"], 1.])
                pen = ImageDraw.Draw(board)
                _dot(
                    pen,
                    (round(left + src[0]*liveimg.width/livemask.shape[1]),
                     round(top + src[1]*liveimg.height/livemask.shape[0])),
                    "#ffc958", "ROBERTO"
                )
            except np.linalg.LinAlgError:
                pass
        result["overlay_mode"] = "side_by_side_not_registered"
        result["reason"] = "Referenz-Screenshot ohne Original-Kalibrierung" if ref_t is None else "Live-Kalibrierung fehlt"
    else:
        transform = np.linalg.inv(live_t) @ ref_t
        coeffs = (
            float(transform[0, 0]), float(transform[0, 1]), float(transform[0, 2]),
            float(transform[1, 0]), float(transform[1, 1]), float(transform[1, 2]),
        )
        aligned = Image.fromarray((livemask * 255).astype("uint8")).transform(
            (refmask.shape[1], refmask.shape[0]),
            Image.Transform.AFFINE, coeffs,
            resample=Image.Resampling.NEAREST, fillcolor=0,
        )
        transformed_mask = np.asarray(aligned) > 127
        n_live = int(transformed_mask.sum())
        # Slight wall-edge tolerance, never used as physical clearance.
        ref_dilated = np.asarray(
            Image.fromarray((refmask * 255).astype("uint8")).filter(
                __import__("PIL.ImageFilter", fromlist=["MaxFilter"]).MaxFilter(7)
            )
        ) > 127
        overlap = float((transformed_mask & ref_dilated).sum() / max(1, n_live))
        result["observed_pixels"] = n_live
        result["floor_overlap_ratio"] = round(overlap, 3)
        result["visual_alignment_candidate"] = n_live >= 200 and overlap >= 0.75
        # Absolute frame of reference in reference image coordinates.
        canvas = _floor_render(refmask, "#567b91")
        image_data = np.asarray(canvas).copy()
        image_data[transformed_mask] = (85, 214, 225)
        canvas = Image.fromarray(image_data, "RGB")
        draw = ImageDraw.Draw(canvas)
        inv_ref = np.linalg.inv(ref_t)
        if robot:
            px = inv_ref @ np.array([robot["x"], robot["y"], 1.])
            if 0 <= px[0] < canvas.width and 0 <= px[1] < canvas.height:
                _dot(draw, (round(px[0]), round(px[1])), "#ffca65", "Roberto")
        if charger:
            px = inv_ref @ np.array([charger["x"], charger["y"], 1.])
            if 0 <= px[0] < canvas.width and 0 <= px[1] < canvas.height:
                _dot(draw, (round(px[0]), round(px[1])), "#a4f49c", "Dock", radius=5)
        canvas = _fit_in(canvas, (1000, 900))
        board = Image.new("RGB", (1020, canvas.height+60), "#0d1b2a")
        board.paste(canvas, ((1020-canvas.width)//2, 40))
        ImageDraw.Draw(board).text(
            (16, 13),
            "REFERENZ: grau   LIVE: tuerkis   ROBOTER: gelb   (NUR DIAGNOSE)",
            fill="#ffffff",
        )
        result["overlay_mode"] = "world_calibrated_preview"
        if not result["visual_alignment_candidate"]:
            result["reason"] = "Ueberlagerung geometrisch nicht bestaetigt"
        else:
            result["reason"] = "Visuelle Ueberlagerung plausibel, physische Position ungeprueft"
    buf = BytesIO()
    board.save(buf, format="PNG", optimize=True)
    return buf.getvalue(), result
