"""Bounded 90-degree scan registration for *diagnostic use only*.

The native Xiaomi map coordinate frame can rotate between cleaning runs.
Map calibration alone describes pixels->world for ONE run, not an enduring
world frame. This module never produces authorization to command the vacuum.
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter

MAX_SEARCH_EDGE = 360
OFFSETS_MM = (-300, -150, 0, 150, 300)
ROTATIONS = (0, 90, 180, 270)


def _translation(dx, dy):
    m = np.eye(3, dtype=float)
    m[0, 2] = dx
    m[1, 2] = dy
    return m


def _rotate(angle):
    a = np.deg2rad(angle)
    c, s = round(float(np.cos(a))), round(float(np.sin(a)))
    return np.array([[c, -s, 0.], [s, c, 0.], [0., 0., 1.]])


def _small_mask(mask):
    height, width = mask.shape
    scale = min(1., MAX_SEARCH_EDGE / max(height, width))
    new_width = max(1, int(round(width * scale)))
    new_height = max(1, int(round(height * scale)))
    small = Image.fromarray((mask * 255).astype("uint8")).resize(
        (new_width, new_height), Image.Resampling.NEAREST,
    )
    # Convert small-image pixels to original-image pixels.
    to_original = np.diag([width / new_width, height / new_height, 1.])
    return small, to_original


def _warp(mask_image, target_size, destination_pixel_to_source_pixel):
    m = destination_pixel_to_source_pixel
    return np.asarray(mask_image.transform(
        target_size,
        Image.Transform.AFFINE,
        (float(m[0, 0]), float(m[0, 1]), float(m[0, 2]),
         float(m[1, 0]), float(m[1, 1]), float(m[1, 2])),
        resample=Image.Resampling.NEAREST,
        fillcolor=0,
    )) > 127


def estimate_registration(refmask, livemask, ref_t, live_t,
                          reference_dock=None, live_dock=None):
    """Find a *candidate* orientation/translation around the fixed dock.

    Returns matrices for rendering, plus scores and diagnostics.
    A shape match is NOT enough to verify a physical coordinate transform.
    """
    refdock = reference_dock or {"x": 25500, "y": 25500}
    livedock = live_dock or {"x": 25500, "y": 25500}
    anchor_assumed = reference_dock is None or live_dock is None
    ref_origin = np.array([float(refdock["x"]), float(refdock["y"])])
    live_origin = np.array([float(livedock["x"]), float(livedock["y"])])
    if not np.isfinite(ref_origin).all() or not np.isfinite(live_origin).all():
        raise ValueError("Invalid dock coordinates")

    ref_small, ref_px_to_orig = _small_mask(refmask)
    live_small, live_px_to_orig = _small_mask(livemask)
    ref_small_t = ref_t @ ref_px_to_orig
    live_small_t = live_t @ live_px_to_orig
    inv_live_small = np.linalg.inv(live_small_t)
    reference_bool = np.asarray(ref_small) > 127
    # Distance tolerance compensates only a few image pixels of wall noise;
    # never extrapolate this tolerance to safe obstacle clearance.
    reference_near = np.asarray(
        ref_small.filter(ImageFilter.MaxFilter(3))
    ) > 127

    total_live = int(np.count_nonzero(np.asarray(live_small) > 127))
    records = []
    for rotation in ROTATIONS:
        best = None
        rot = _rotate(rotation)
        def evaluate(dx, dy):
            mapping = (
                _translation(ref_origin[0] + dx, ref_origin[1] + dy)
                @ rot
                @ _translation(-live_origin[0], -live_origin[1])
            )
            src = inv_live_small @ np.linalg.inv(mapping) @ ref_small_t
            projected = _warp(live_small, ref_small.size, src)
            support = int(np.count_nonzero(projected))
            coverage = support / max(1, total_live)
            # Never reward a rotation by clipping 55% of the scanned walls.
            if total_live < 80 or support < 70 or coverage < 0.85:
                return None
            matched = int(np.count_nonzero(projected & reference_near))
            # Intentionally divide by the FULL live mask, not only the
            # visible cropped portion. This penalizes incorrect placement.
            score = matched / total_live
            ranked = score - 0.004 * (abs(dx) + abs(dy)) / 300
            return {
                "rotation_degrees": rotation,
                "shift_mm": [dx, dy],
                "score": round(score, 4),
                "ranked": ranked,
                "observed_pixels": support,
                "coverage_ratio": round(coverage, 4),
                "mapping": mapping,
            }

        for dx in OFFSETS_MM:
            for dy in OFFSETS_MM:
                candidate = evaluate(dx, dy)
                if candidate and (best is None or candidate["ranked"] > best["ranked"]):
                    best = candidate
        # Refine near the coarse candidate, without a global unbounded search.
        if best is not None:
            center_x, center_y = best["shift_mm"]
            for dx in range(center_x - 100, center_x + 101, 50):
                for dy in range(center_y - 100, center_y + 101, 50):
                    if abs(dx) > 400 or abs(dy) > 400:
                        continue
                    candidate = evaluate(dx, dy)
                    if candidate and candidate["ranked"] > best["ranked"]:
                        best = candidate
        if best is not None:
            records.append(best)
    records.sort(key=lambda item: item["ranked"], reverse=True)
    if not records:
        return {
            "found": False,
            "reason": "Kartenbereich zu klein oder außerhalb der Referenz",
            "anchor_assumed": anchor_assumed,
            "candidates": [],
        }
    best, second = records[0], records[1] if len(records) > 1 else None
    gap = best["score"] - (second["score"] if second else 0.0)
    # Confidence in visual orientation requires both a strong match and
    # uniqueness among 4 rotations. A partial/near-symmetric room is often
    # intrinsically ambiguous. Dock anchors must be observed, not guessed.
    shape_distinct = (
        best["score"] >= 0.78
        and gap >= 0.10
        and best["observed_pixels"] >= 180
        and best["coverage_ratio"] >= 0.90
    )
    world_map = best["mapping"]
    ref_to_live = np.linalg.inv(live_t) @ np.linalg.inv(world_map) @ ref_t
    return {
        "found": True,
        "rotation_degrees": best["rotation_degrees"],
        "shift_mm": best["shift_mm"],
        "best_score": best["score"],
        "runner_score": second["score"] if second else None,
        "score_gap": round(gap, 4),
        "observed_pixels": best["observed_pixels"],
        "coverage_ratio": best["coverage_ratio"],
        "candidate_distinct": shape_distinct,
        "anchor_assumed": anchor_assumed,
        "world_live_to_ref": world_map,
        "ref_to_live_pixel": ref_to_live,
        "candidates": [
            {"rotation_degrees": r["rotation_degrees"],
             "score": r["score"], "shift_mm": r["shift_mm"],
             "coverage_ratio": r["coverage_ratio"]}
            for r in records
        ],
        "navigation_coordinates_verified": False,
    }


def warp_full(livemask, reference_shape, pixel_transform):
    """Apply a selected *diagnostic* candidate to original-resolution masks."""
    src = Image.fromarray((livemask * 255).astype("uint8"))
    return _warp(
        src, (reference_shape[1], reference_shape[0]), pixel_transform
    )
