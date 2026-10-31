"""Prepare private historical map screenshots for read-only comparison.

This module does not send any coordinates or commands to a vacuum.
"""
from __future__ import annotations

from io import BytesIO

import numpy as np
from PIL import Image, ImageFilter, ImageOps, UnidentifiedImageError

MAX_INPUT_BYTES = 10_000_000
MAX_PIXELS = 16_000_000
MAX_OUTPUT_EDGE = 1200


def prepare_reference_image(raw: bytes) -> tuple[bytes, dict]:
    """Validate a user-uploaded image and normalize Xiaomi history screenshots."""
    if not raw or len(raw) > MAX_INPUT_BYTES:
        raise ValueError("Bild muss kleiner als 10 MB sein")

    try:
        with Image.open(BytesIO(raw)) as source:
            if source.width * source.height > MAX_PIXELS:
                raise ValueError("Bildauflösung zu groß (maximal 16 Megapixel)")
            if source.format not in ("PNG", "JPEG", "WEBP"):
                raise ValueError("Nur PNG, JPEG oder WEBP unterstützt")
            img = ImageOps.exif_transpose(source).convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("Keine gültige Bilddatei") from exc

    img.thumbnail((MAX_OUTPUT_EDGE, MAX_OUTPUT_EDGE), Image.Resampling.LANCZOS)
    rgb = np.asarray(img, dtype=np.int16)
    red, green, blue = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    bright_floor = (
        (blue >= 190)
        & (green >= 135)
        & ((blue - red) >= 60)
        & ((green - red) >= 55)
        & ((blue - green) >= 20)
    )
    share = float(np.mean(bright_floor))
    method = "Originalbild (keine sichere Xiaomi-Farbmaske erkannt)"
    if 0.02 <= share <= 0.70:
        mask_image = Image.fromarray((bright_floor * 255).astype("uint8"), "L")
        mask_image = mask_image.filter(ImageFilter.MedianFilter(3))
        mask = np.asarray(mask_image) >= 128
        ys, xs = np.where(mask)
        if len(xs) > 100:
            left = max(0, int(xs.min()) - 10)
            right = min(img.width, int(xs.max()) + 11)
            top = max(0, int(ys.min()) - 10)
            bottom = min(img.height, int(ys.max()) + 11)
            alpha = Image.fromarray((mask * 255).astype("uint8"), "L")
            silhouette = Image.new("RGBA", img.size, (255, 255, 255, 0))
            silhouette.putalpha(alpha)
            img_out = silhouette.crop((left, top, right, bottom))
            method = "Xiaomi-Screenshot: App-Oberfläche entfernt, Bodenmaske extrahiert"
        else:
            img_out = img
    else:
        img_out = img

    output = BytesIO()
    img_out.save(output, format="PNG", optimize=True)
    return output.getvalue(), {
        "method": method,
        "width": img_out.width,
        "height": img_out.height,
        "source_image_only": True,
    }
