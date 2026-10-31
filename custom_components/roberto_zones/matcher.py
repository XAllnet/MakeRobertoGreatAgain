"""Low-resolution image silhouette comparison. Not safe for robot navigation."""
from __future__ import annotations

from io import BytesIO

import numpy as np
from PIL import Image, ImageOps

SIZE = 96


def _silhouette(source: bytes) -> tuple[np.ndarray, float]:
    """Extract bright floor areas from dark map images at low resolution."""
    with Image.open(BytesIO(source)) as raw:
        original = ImageOps.exif_transpose(raw)
        original.thumbnail((512, 512), Image.Resampling.BILINEAR)
        rgba = np.asarray(original.convert("RGBA"), dtype=np.uint8)
        rgb = rgba[:, :, :3].astype(np.float32)
        alpha = rgba[:, :, 3]
        if float(np.mean(alpha < 245)) > 0.05:
            mask = alpha >= 90
        else:
            h, w = rgb.shape[:2]
            thick_h = max(2, h // 25)
            thick_w = max(2, w // 25)
            border = np.concatenate([
                rgb[:thick_h].reshape(-1, 3),
                rgb[-thick_h:].reshape(-1, 3),
                rgb[:, :thick_w].reshape(-1, 3),
                rgb[:, -thick_w:].reshape(-1, 3),
            ])
            background = np.median(border, axis=0)
            diff = np.sqrt(np.sum((rgb - background) ** 2, axis=2))
            mask = diff > 72

        if mask.sum() < 80:
            raise ValueError("Kartensilhouette nicht erkennbar")
        ys, xs = np.where(mask)
        x0, x1 = xs.min(), xs.max() + 1
        y0, y1 = ys.min(), ys.max() + 1
        region = mask[y0:y1, x0:x1]
        rh, rw = region.shape
        width = max(1, round(rw * (SIZE - 8) / max(rw, rh)))
        height = max(1, round(rh * (SIZE - 8) / max(rw, rh)))
        thumb = Image.fromarray((region * 255).astype(np.uint8)).resize(
            (width, height), Image.Resampling.NEAREST
        )
        field = np.zeros((SIZE, SIZE), dtype=np.bool_)
        dx, dy = (SIZE - width) // 2, (SIZE - height) // 2
        field[dy:dy + height, dx:dx + width] = np.asarray(thumb) > 127
        return field, float(mask.mean())


def compare(current_bytes: bytes, reference_bytes: bytes) -> dict:
    """Return unverified orientation candidates, never a navigation authorization."""
    observed, coverage = _silhouette(current_bytes)
    reference, _ = _silhouette(reference_bytes)
    scores = []

    for turn in range(4):
        rotated = np.rot90(observed, turn)
        best = -1.0
        for dy in range(-12, 13, 3):
            for dx in range(-12, 13, 3):
                yy0, yy1 = max(0, dy), min(SIZE, SIZE + dy)
                xx0, xx1 = max(0, dx), min(SIZE, SIZE + dx)
                chunk = rotated[yy0 - dy:yy1 - dy, xx0 - dx:xx1 - dx]
                target = reference[yy0:yy1, xx0:xx1]
                inter = np.count_nonzero(chunk & target)
                union = np.count_nonzero(chunk | target)
                metric = inter / union if union else 0.0
                best = max(best, metric)
        scores.append(float(round(best, 4)))

    order = sorted(range(4), key=lambda i: scores[i], reverse=True)
    best, runner = scores[order[0]], scores[order[1]]
    candidate = best >= 0.64 and best - runner >= 0.09 and coverage >= 0.03
    return {
        "candidate_rotation_degrees": (order[0] * 90) % 360,
        "scores_by_rotation_0_90_180_270": scores,
        "best_score": best,
        "runner_up_score": runner,
        "candidate_is_distinct": bool(candidate),
        "observed_mask_coverage": round(coverage, 4),
        "navigation_coordinates_verified": False,
        "note": "Nur Bildheuristik; kein Dock- oder Navigationsabgleich.",
    }
