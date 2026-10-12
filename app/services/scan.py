"""Scan preprocessing for image uploads before OCR (Pillow only).

EXIF orientation -> grayscale -> autocontrast -> deskew (projection profile)
-> crop blank margins. Memory stays bounded: JPEGs decode reduced via
`draft` and every image is capped at MAX_SIDE pixels.
"""

from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageOps

MAX_SIDE = 3000
INK = 110  # darker than this (after autocontrast) counts as ink


def _profile_score(ink: Image.Image, angle: float) -> float:
    rotated = ink.rotate(angle, resample=Image.Resampling.BILINEAR, fillcolor=0)
    rows = rotated.resize((1, rotated.height), Image.Resampling.BOX).get_flattened_data()
    return sum((a - b) ** 2 for a, b in zip(rows, rows[1:]))


def estimate_skew(gray: Image.Image, limit: float = 10.0) -> float:
    """Rotation (degrees, counter-clockwise) that makes text lines horizontal.

    ponytail: brute-force projection profile on an 800 px copy (~60 rotations);
    switch to a Hough transform if it ever shows in profiles.
    """
    small = ImageOps.grayscale(gray)
    small.thumbnail((800, 800))
    ink = small.point(lambda v: 255 if v < INK else 0)
    coarse = max((a for a in range(-int(limit), int(limit) + 1)), key=lambda a: _profile_score(ink, a))
    return max((coarse + step / 10 for step in range(-10, 11)), key=lambda a: _profile_score(ink, a))


def preprocess_image(data: bytes) -> bytes:
    """Return a cleaned grayscale PNG ready for OCR."""
    with Image.open(BytesIO(data)) as image:
        image.draft("L", (MAX_SIDE, MAX_SIDE))
        gray = ImageOps.grayscale(ImageOps.exif_transpose(image))
    gray.thumbnail((MAX_SIDE, MAX_SIDE))
    gray = ImageOps.autocontrast(gray, cutoff=1)
    angle = estimate_skew(gray)
    if abs(angle) >= 0.2:
        gray = gray.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=255)
    box = gray.point(lambda v: 255 if v < INK else 0).getbbox()
    if box:
        pad = max(gray.size) // 50
        gray = gray.crop((max(box[0] - pad, 0), max(box[1] - pad, 0),
                          min(box[2] + pad, gray.width), min(box[3] + pad, gray.height)))
    out = BytesIO()
    gray.save(out, format="PNG")
    return out.getvalue()
