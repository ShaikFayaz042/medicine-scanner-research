"""Coordinate conversions used by every extraction backend.

Extraction item boxes are normalized to the visible page, after /Rotate. PyMuPDF
text spans and clip rectangles use unrotated coordinates; table boxes and pixmaps
use visible coordinates.
"""
from __future__ import annotations

import pymupdf


def to_visible(page: pymupdf.Page, rect: pymupdf.Rect | tuple[float, ...]) -> pymupdf.Rect:
    """Convert an unrotated PyMuPDF rectangle to visible page coordinates."""
    return pymupdf.Rect(rect) * page.rotation_matrix


def to_unrotated(page: pymupdf.Page, rect: pymupdf.Rect | tuple[float, ...]) -> pymupdf.Rect:
    """Convert a visible rectangle to the coordinate space required by get_text(clip=...)."""
    return pymupdf.Rect(rect) * page.derotation_matrix


def normalize(page: pymupdf.Page, rect: pymupdf.Rect | tuple[float, ...]) -> tuple[float, float, float, float]:
    """Convert a visible-space point rectangle to a bounded 0..1 page box."""
    box = pymupdf.Rect(rect)
    width, height = page.rect.width, page.rect.height
    if width <= 0 or height <= 0:
        raise ValueError(f"page has invalid visible dimensions: {width}x{height}")
    return (
        round(max(0.0, min(1.0, box.x0 / width)), 6),
        round(max(0.0, min(1.0, box.y0 / height)), 6),
        round(max(0.0, min(1.0, box.x1 / width)), 6),
        round(max(0.0, min(1.0, box.y1 / height)), 6),
    )
