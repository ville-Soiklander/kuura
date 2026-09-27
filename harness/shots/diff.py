"""Image comparison with tolerance and masking.

Implements the tolerance-based comparison rule from the harness contract:
pixels differ when their largest channel difference exceeds tolerance AND
they lie outside every mask; an image passes when differing pixels are
at most max_diff_ratio of the total.

Also generates visual diff images for review.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .pngio import read_png, write_png


@dataclass(frozen=True)
class Rect:
    """Axis-aligned rectangle in physical pixels."""

    x0: int
    y0: int
    x1: int
    y1: int

    def contains(self, x: int, y: int) -> bool:
        """Check if point (x, y) is inside this rectangle."""
        return self.x0 <= x < self.x1 and self.y0 <= y < self.y1


@dataclass(frozen=True)
class DiffResult:
    """Result of image comparison."""

    passed: bool  # True if differing_pixels <= max_diff_ratio * total_pixels
    differing_pixels: int
    total_pixels: int
    ratio: float  # differing_pixels / total_pixels
    max_delta: int  # largest channel difference among all pixels
    bbox: tuple[int, int, int, int] | None  # (x0, y0, x1, y1) of differing pixels, or None


def compare_images(
    actual: Path,
    golden: Path,
    tolerance: int,
    max_diff_ratio: float,
    masks: list[Rect] | None = None,
) -> DiffResult:
    """
    Compare two PNG images pixel by pixel with tolerance and masking.

    A pixel is considered to differ if:
    1. The largest channel difference exceeds tolerance, AND
    2. The pixel is outside every mask rectangle.

    Args:
        actual: Path to actual image.
        golden: Path to golden image.
        tolerance: Per-channel difference threshold (0-255); delta <= tolerance is equal.
        max_diff_ratio: Maximum allowed ratio of differing pixels (0.0-1.0).
        masks: List of rectangular regions to ignore (checked with <, so x1 is exclusive).

    Returns:
        DiffResult with pass/fail status, metrics and bounding box.

    Raises:
        ValueError: if images differ in size or have unsupported format.
    """
    if masks is None:
        masks = []

    width_a, height_a, pixels_a = read_png(actual)
    width_g, height_g, pixels_g = read_png(golden)

    if (width_a, height_a) != (width_g, height_g):
        raise ValueError(f"image size mismatch: {width_a}x{height_a} vs {width_g}x{height_g}")

    width, height = width_a, height_a
    total_pixels = width * height
    differing = 0
    max_delta_found = 0
    bbox_x0, bbox_y0, bbox_x1, bbox_y1 = width, height, -1, -1

    # WHY: Compare row by row, skipping identical rows entirely for speed.
    # Most rows will be unchanged, so this fast path avoids per-pixel overhead.
    stride = width * 3
    for y in range(height):
        row_start = y * stride
        row_end = row_start + stride
        row_a = pixels_a[row_start:row_end]
        row_g = pixels_g[row_start:row_end]

        if row_a == row_g:
            continue  # Fast path: identical rows

        # Slow path: per-pixel comparison
        for x in range(width):
            i = x * 3
            r_a, g_a, b_a = row_a[i], row_a[i + 1], row_a[i + 2]
            r_g, g_g, b_g = row_g[i], row_g[i + 1], row_g[i + 2]

            delta = max(abs(r_a - r_g), abs(g_a - g_g), abs(b_a - b_g))
            if delta > tolerance:
                # Check if this pixel is masked
                masked = any(mask.contains(x, y) for mask in masks)
                if not masked:
                    differing += 1
                    max_delta_found = max(max_delta_found, delta)
                    bbox_x0, bbox_y0 = min(bbox_x0, x), min(bbox_y0, y)
                    bbox_x1, bbox_y1 = max(bbox_x1, x), max(bbox_y1, y)

    ratio = differing / total_pixels if total_pixels > 0 else 0.0
    passed = differing <= max_diff_ratio * total_pixels

    bbox = (bbox_x0, bbox_y0, bbox_x1, bbox_y1) if differing > 0 else None

    return DiffResult(
        passed=passed,
        differing_pixels=differing,
        total_pixels=total_pixels,
        ratio=ratio,
        max_delta=max_delta_found,
        bbox=bbox,
    )


def write_diff_image(
    actual: Path,
    golden: Path,
    out: Path,
    tolerance: int,
    masks: list[Rect] | None = None,
) -> None:
    """
    Write a visual diff image: actual dimmed to 35%, differing pixels red, masked area blue-tinted.

    Args:
        actual: Path to actual image.
        golden: Path to golden image (for pixel difference calculation).
        out: Output PNG path.
        tolerance: Per-channel difference threshold.
        masks: List of rectangular regions to ignore.

    Raises:
        ValueError: if images differ in size or have unsupported format.
    """
    if masks is None:
        masks = []

    width_a, height_a, pixels_a = read_png(actual)
    width_g, height_g, pixels_g = read_png(golden)

    if (width_a, height_a) != (width_g, height_g):
        raise ValueError(f"image size mismatch: {width_a}x{height_a} vs {width_g}x{height_g}")

    width, height = width_a, height_a
    output = bytearray(width * height * 3)

    # WHY: Build the diff image by processing each pixel once, checking both
    # the actual/golden delta and mask membership. Red for differences, blue tint for masks.
    stride = width * 3
    for y in range(height):
        row_start = y * stride
        row_end = row_start + stride
        row_a = pixels_a[row_start:row_end]
        row_g = pixels_g[row_start:row_end]

        for x in range(width):
            i = x * 3
            r_a, g_a, b_a = row_a[i], row_a[i + 1], row_a[i + 2]
            r_g, g_g, b_g = row_g[i], row_g[i + 1], row_g[i + 2]

            delta = max(abs(r_a - r_g), abs(g_a - g_g), abs(b_a - b_g))

            masked = any(mask.contains(x, y) for mask in masks)

            if masked:
                # Masked area: tint actual with faint blue (add 20 to blue channel, dim RGB to 35%)
                output_idx = row_start + i
                output[output_idx] = int(r_a * 0.35)
                output[output_idx + 1] = int(g_a * 0.35)
                output[output_idx + 2] = int(b_a * 0.35 + 20)
            elif delta > tolerance:
                # Differing pixel: pure red
                output_idx = row_start + i
                output[output_idx] = 255
                output[output_idx + 1] = 0
                output[output_idx + 2] = 0
            else:
                # Matching pixel: dim actual to 35%
                output_idx = row_start + i
                output[output_idx] = int(r_a * 0.35)
                output[output_idx + 1] = int(g_a * 0.35)
                output[output_idx + 2] = int(b_a * 0.35)

    write_png(out, width, height, bytes(output))
