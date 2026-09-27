"""Tests for image comparison module."""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.shots.diff import Rect, compare_images, write_diff_image
from harness.shots.pngio import write_png


def _make_image(tmp_path: Path, name: str, width: int, height: int, color: tuple[int, int, int]) -> Path:
    """Helper: create a solid-color image."""
    rgb = bytes(color * (width * height))
    path = tmp_path / name
    write_png(path, width, height, rgb)
    return path


def test_compare_identical_images(tmp_path: Path) -> None:
    """Compare two identical images."""
    img1 = _make_image(tmp_path, "img1.png", 40, 30, (100, 150, 200))
    img2 = _make_image(tmp_path, "img2.png", 40, 30, (100, 150, 200))

    result = compare_images(img1, img2, tolerance=0, max_diff_ratio=0.0)

    assert result.passed
    assert result.differing_pixels == 0
    assert result.total_pixels == 40 * 30
    assert result.ratio == 0.0
    assert result.max_delta == 0
    assert result.bbox is None


def test_compare_tolerance_boundary(tmp_path: Path) -> None:
    """Test tolerance boundary: delta == tolerance is equal, delta > tolerance differs."""
    width, height = 40, 30
    rgb1 = bytes([100, 100, 100] * (width * height))
    rgb2 = bytearray(rgb1)
    # Change one pixel to have delta exactly at tolerance
    rgb2[0] = 103  # delta = 3
    rgb2_bytes = bytes(rgb2)

    path1 = tmp_path / "img1.png"
    path2 = tmp_path / "img2.png"
    write_png(path1, width, height, rgb1)
    write_png(path2, width, height, rgb2_bytes)

    # With tolerance=3, delta=3 should be equal
    result = compare_images(path1, path2, tolerance=3, max_diff_ratio=0.0)
    assert result.passed
    assert result.differing_pixels == 0

    # With tolerance=2, delta=3 should differ
    result = compare_images(path1, path2, tolerance=2, max_diff_ratio=0.0)
    assert not result.passed
    assert result.differing_pixels == 1
    assert result.max_delta == 3


def test_compare_size_mismatch(tmp_path: Path) -> None:
    """Compare images with different sizes."""
    img1 = _make_image(tmp_path, "img1.png", 40, 30, (100, 150, 200))
    img2 = _make_image(tmp_path, "img2.png", 50, 30, (100, 150, 200))

    with pytest.raises(ValueError, match="size mismatch"):
        compare_images(img1, img2, tolerance=0, max_diff_ratio=0.0)


def test_compare_max_diff_ratio(tmp_path: Path) -> None:
    """Test max_diff_ratio threshold."""
    width, height = 100, 100  # 10000 pixels
    rgb1 = bytes([100, 100, 100] * (width * height))
    rgb2 = bytearray(rgb1)
    # Change 5 pixels to differ
    for i in range(5):
        rgb2[i * 3] = 200

    path1 = tmp_path / "img1.png"
    path2 = tmp_path / "img2.png"
    write_png(path1, width, height, rgb1)
    write_png(path2, width, height, bytes(rgb2))

    # 5 / 10000 = 0.0005, exactly at default limit
    result = compare_images(path1, path2, tolerance=0, max_diff_ratio=0.0005)
    assert result.passed
    assert result.differing_pixels == 5
    assert result.ratio == 0.0005

    # One less pixel should still pass
    result = compare_images(path1, path2, tolerance=0, max_diff_ratio=0.0006)
    assert result.passed

    # One less ratio should fail
    result = compare_images(path1, path2, tolerance=0, max_diff_ratio=0.0004)
    assert not result.passed


def test_compare_bbox(tmp_path: Path) -> None:
    """Test bounding box of differing pixels."""
    width, height = 40, 30
    rgb1 = bytes([100, 100, 100] * (width * height))
    rgb2 = bytearray(rgb1)

    # Change pixels in a region: x=[10,20), y=[5,15)
    for y in range(5, 15):
        for x in range(10, 20):
            idx = (y * width + x) * 3
            rgb2[idx] = 200

    path1 = tmp_path / "img1.png"
    path2 = tmp_path / "img2.png"
    write_png(path1, width, height, rgb1)
    write_png(path2, width, height, bytes(rgb2))

    result = compare_images(path1, path2, tolerance=0, max_diff_ratio=1.0)
    assert result.differing_pixels == 100  # 10 * 10
    assert result.bbox == (10, 5, 19, 14)  # x1 and y1 are inclusive in our output


def test_compare_masks_simple(tmp_path: Path) -> None:
    """Test that pixels inside masks are ignored."""
    width, height = 40, 30
    rgb1 = bytes([100, 100, 100] * (width * height))
    rgb2 = bytearray(rgb1)

    # Change all pixels in region [10, 20) x [5, 15)
    for y in range(5, 15):
        for x in range(10, 20):
            idx = (y * width + x) * 3
            rgb2[idx] = 200

    path1 = tmp_path / "img1.png"
    path2 = tmp_path / "img2.png"
    write_png(path1, width, height, rgb1)
    write_png(path2, width, height, bytes(rgb2))

    # Without mask: 100 differing pixels
    result = compare_images(path1, path2, tolerance=0, max_diff_ratio=1.0)
    assert result.differing_pixels == 100

    # With mask covering the region: 0 differing pixels
    mask = Rect(10, 5, 20, 15)
    result = compare_images(path1, path2, tolerance=0, max_diff_ratio=0.0, masks=[mask])
    assert result.passed
    assert result.differing_pixels == 0
    assert result.bbox is None


def test_compare_masks_partial(tmp_path: Path) -> None:
    """Test masks that partially cover differences."""
    width, height = 40, 30
    rgb1 = bytes([100, 100, 100] * (width * height))
    rgb2 = bytearray(rgb1)

    # Change pixels in [10, 20) x [5, 15)
    for y in range(5, 15):
        for x in range(10, 20):
            idx = (y * width + x) * 3
            rgb2[idx] = 200

    path1 = tmp_path / "img1.png"
    path2 = tmp_path / "img2.png"
    write_png(path1, width, height, rgb1)
    write_png(path2, width, height, bytes(rgb2))

    # Mask covers only half: [10, 15) x [5, 15)
    mask = Rect(10, 5, 15, 15)
    result = compare_images(path1, path2, tolerance=0, max_diff_ratio=1.0, masks=[mask])
    # Only pixels in [15, 20) x [5, 15) should count: 5 * 10 = 50
    assert result.differing_pixels == 50


def test_compare_multiple_masks(tmp_path: Path) -> None:
    """Test multiple mask rectangles."""
    width, height = 40, 30
    rgb1 = bytes([100, 100, 100] * (width * height))
    rgb2 = bytearray(rgb1)

    # Change pixels at two separate regions
    for y in range(5, 10):
        for x in range(10, 15):
            idx = (y * width + x) * 3
            rgb2[idx] = 200
    for y in range(20, 25):
        for x in range(20, 25):
            idx = (y * width + x) * 3
            rgb2[idx] = 200

    path1 = tmp_path / "img1.png"
    path2 = tmp_path / "img2.png"
    write_png(path1, width, height, rgb1)
    write_png(path2, width, height, bytes(rgb2))

    # Without masks: 50 differing pixels
    result = compare_images(path1, path2, tolerance=0, max_diff_ratio=1.0)
    assert result.differing_pixels == 50

    # With both regions masked
    masks = [Rect(10, 5, 15, 10), Rect(20, 20, 25, 25)]
    result = compare_images(path1, path2, tolerance=0, max_diff_ratio=0.0, masks=masks)
    assert result.passed
    assert result.differing_pixels == 0


def test_write_diff_image(tmp_path: Path) -> None:
    """Test diff image generation."""
    width, height = 40, 30
    rgb1 = bytes([100, 100, 100] * (width * height))
    rgb2 = bytearray(rgb1)
    # Change one pixel
    rgb2[0] = 200
    rgb2[1] = 200
    rgb2[2] = 200

    path1 = tmp_path / "img1.png"
    path2 = tmp_path / "img2.png"
    write_png(path1, width, height, rgb1)
    write_png(path2, width, height, bytes(rgb2))

    out_path = tmp_path / "diff.png"
    write_diff_image(path1, path2, out_path, tolerance=0)

    # Read back the diff image
    from harness.shots.pngio import read_png as read_png_direct

    w, h, diff_rgb = read_png_direct(out_path)
    assert (w, h) == (width, height)

    # First pixel should be red (255, 0, 0) since it differs
    assert diff_rgb[0:3] == bytes([255, 0, 0])

    # Other pixels should be dimmed to 35% (100 * 0.35 = 35)
    assert diff_rgb[3:6] == bytes([35, 35, 35])


def test_write_diff_image_with_mask(tmp_path: Path) -> None:
    """Test diff image with masked area."""
    width, height = 40, 30
    rgb1 = bytes([100, 100, 100] * (width * height))
    rgb2 = bytearray(rgb1)

    # Change pixel at (10, 10) and (20, 20)
    idx1 = (10 * width + 10) * 3
    rgb2[idx1] = 200
    idx2 = (20 * width + 20) * 3
    rgb2[idx2] = 200

    path1 = tmp_path / "img1.png"
    path2 = tmp_path / "img2.png"
    write_png(path1, width, height, rgb1)
    write_png(path2, width, height, bytes(rgb2))

    out_path = tmp_path / "diff.png"
    mask = Rect(10, 10, 11, 11)  # Covers (10, 10)
    write_diff_image(path1, path2, out_path, tolerance=0, masks=[mask])

    from harness.shots.pngio import read_png as read_png_direct

    w, h, diff_rgb = read_png_direct(out_path)

    # Pixel at (10, 10) should be masked (blue tint): ~35% + 20 on blue
    masked_idx = (10 * width + 10) * 3
    assert diff_rgb[masked_idx] == 35  # Red channel: 100 * 0.35
    assert diff_rgb[masked_idx + 1] == 35  # Green channel
    assert diff_rgb[masked_idx + 2] == 55  # Blue channel: 100 * 0.35 + 20

    # Pixel at (20, 20) should be red
    diff_idx = (20 * width + 20) * 3
    assert diff_rgb[diff_idx : diff_idx + 3] == bytes([255, 0, 0])


def test_write_diff_image_size_mismatch(tmp_path: Path) -> None:
    """Test diff image with mismatched image sizes."""
    img1 = _make_image(tmp_path, "img1.png", 40, 30, (100, 100, 100))
    img2 = _make_image(tmp_path, "img2.png", 50, 30, (100, 100, 100))

    out_path = tmp_path / "diff.png"

    with pytest.raises(ValueError, match="size mismatch"):
        write_diff_image(img1, img2, out_path, tolerance=0)
