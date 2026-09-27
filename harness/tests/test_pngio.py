"""Tests for PNG I/O module."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest

from harness.shots.pngio import PNG_SIGNATURE, read_png, write_png, _crc


def _write_png_chunks(path: Path, chunks: list[tuple[bytes, bytes]]) -> None:
    """Helper: write raw PNG with given chunks (type, body)."""
    data = bytearray(PNG_SIGNATURE)
    for chunk_type, chunk_body in chunks:
        data.extend(struct.pack(">I", len(chunk_body)))
        data.extend(chunk_type)
        data.extend(chunk_body)
        data.extend(struct.pack(">I", _crc(chunk_type + chunk_body)))
    path.write_bytes(bytes(data))


def test_read_png_rgb_small(tmp_path: Path) -> None:
    """Read a small RGB PNG (8x8)."""
    width, height = 8, 8
    rgb = bytes([255, 0, 0] * 64)  # Red pixels

    path = tmp_path / "test.png"
    write_png(path, width, height, rgb)

    w, h, data = read_png(path)
    assert (w, h) == (width, height)
    assert data == rgb


def test_read_png_rgba_to_rgb(tmp_path: Path) -> None:
    """Read RGBA PNG: alpha should be dropped."""
    width, height = 2, 2
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # RGBA
    pixel_data = bytearray()
    for _ in range(height):
        pixel_data.append(0)  # filter type: None
        for _ in range(width):
            pixel_data.extend([255, 0, 0, 128])  # RGBA

    idat = zlib.compress(bytes(pixel_data), level=6)

    path = tmp_path / "rgba.png"
    _write_png_chunks(path, [(b"IHDR", ihdr), (b"IDAT", idat), (b"IEND", b"")])

    w, h, data = read_png(path)
    assert (w, h) == (2, 2)
    assert len(data) == 12  # 2*2*3
    # All pixels should be RGB (alpha 128 dropped)
    assert data == bytes([255, 0, 0, 255, 0, 0, 255, 0, 0, 255, 0, 0])


def test_read_png_grayscale_to_rgb(tmp_path: Path) -> None:
    """Read grayscale PNG: should be expanded to RGB."""
    width, height = 2, 2
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)  # Grayscale
    pixel_data = bytearray()
    for _ in range(height):
        pixel_data.append(0)  # filter type: None
        for _ in range(width):
            pixel_data.append(128)  # Gray value

    idat = zlib.compress(bytes(pixel_data), level=6)

    path = tmp_path / "gray.png"
    _write_png_chunks(path, [(b"IHDR", ihdr), (b"IDAT", idat), (b"IEND", b"")])

    w, h, data = read_png(path)
    assert (w, h) == (2, 2)
    assert len(data) == 12
    # Grayscale value 128 should be replicated to RGB
    assert data == bytes([128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128])


def test_read_png_filter_type_0(tmp_path: Path) -> None:
    """Read PNG with filter type 0 (None)."""
    width, height = 2, 2
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    pixel_data = bytearray()
    for _ in range(height):
        pixel_data.append(0)  # filter type: None
        pixel_data.extend([255, 0, 0, 0, 255, 0])  # Two RGB pixels

    idat = zlib.compress(bytes(pixel_data), level=6)

    path = tmp_path / "filter0.png"
    _write_png_chunks(path, [(b"IHDR", ihdr), (b"IDAT", idat), (b"IEND", b"")])

    w, h, data = read_png(path)
    assert len(data) == 12
    assert data[:6] == bytes([255, 0, 0, 0, 255, 0])


def test_read_png_filter_type_1_sub(tmp_path: Path) -> None:
    """Read PNG with filter type 1 (Sub)."""
    width, height = 2, 2
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    pixel_data = bytearray()
    for _ in range(height):
        pixel_data.append(1)  # filter type: Sub
        # Delta-encoded: first pixel diff, second pixel is relative to first
        pixel_data.extend([255, 0, 0, 1, 255, 0])  # Will be reconstructed to [255,0,0], [256,255,0] -> [0,255,0]

    idat = zlib.compress(bytes(pixel_data), level=6)

    path = tmp_path / "filter1.png"
    _write_png_chunks(path, [(b"IHDR", ihdr), (b"IDAT", idat), (b"IEND", b"")])

    w, h, data = read_png(path)
    assert len(data) == 12


def test_read_png_filter_type_2_up(tmp_path: Path) -> None:
    """Read PNG with filter type 2 (Up)."""
    width, height = 2, 2
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    pixel_data = bytearray()
    for row in range(height):
        pixel_data.append(2)  # filter type: Up
        if row == 0:
            pixel_data.extend([100, 100, 100, 100, 100, 100])
        else:
            pixel_data.extend([50, 50, 50, 50, 50, 50])  # Will add to row above

    idat = zlib.compress(bytes(pixel_data), level=6)

    path = tmp_path / "filter2.png"
    _write_png_chunks(path, [(b"IHDR", ihdr), (b"IDAT", idat), (b"IEND", b"")])

    w, h, data = read_png(path)
    assert len(data) == 12
    # First row: 100, 100, 100 per pixel
    assert data[:6] == bytes([100, 100, 100, 100, 100, 100])
    # Second row: 100+50=150 per channel
    assert data[6:12] == bytes([150, 150, 150, 150, 150, 150])


def test_read_png_filter_type_3_average(tmp_path: Path) -> None:
    """Read PNG with filter type 3 (Average)."""
    width, height = 2, 2
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    pixel_data = bytearray()
    for row in range(height):
        pixel_data.append(3)  # filter type: Average
        if row == 0:
            # No pixel above, so average with 0
            pixel_data.extend([100, 100, 100, 100, 100, 100])
        else:
            # Pixel above is [100, 100, 100], left is [100, 100, 100], avg = 100
            pixel_data.extend([0, 0, 0, 0, 0, 0])  # Will be: 100 + (100+100)/2 = 200, etc.

    idat = zlib.compress(bytes(pixel_data), level=6)

    path = tmp_path / "filter3.png"
    _write_png_chunks(path, [(b"IHDR", ihdr), (b"IDAT", idat), (b"IEND", b"")])

    w, h, data = read_png(path)
    assert len(data) == 12


def test_read_png_filter_type_4_paeth(tmp_path: Path) -> None:
    """Read PNG with filter type 4 (Paeth)."""
    width, height = 2, 2
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    pixel_data = bytearray()
    for row in range(height):
        pixel_data.append(4)  # filter type: Paeth
        pixel_data.extend([50, 50, 50, 50, 50, 50])

    idat = zlib.compress(bytes(pixel_data), level=6)

    path = tmp_path / "filter4.png"
    _write_png_chunks(path, [(b"IHDR", ihdr), (b"IDAT", idat), (b"IEND", b"")])

    w, h, data = read_png(path)
    assert len(data) == 12


def test_read_png_crc_failure(tmp_path: Path) -> None:
    """Read PNG with invalid CRC."""
    width, height = 2, 2
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)

    path = tmp_path / "badcrc.png"
    data = bytearray(PNG_SIGNATURE)
    data.extend(struct.pack(">I", 13))  # length
    data.extend(b"IHDR")
    data.extend(ihdr)
    data.extend(struct.pack(">I", 0xdeadbeef))  # Bad CRC

    path.write_bytes(bytes(data))

    with pytest.raises(ValueError, match="CRC mismatch"):
        read_png(path)


def test_read_png_not_png(tmp_path: Path) -> None:
    """Read file that is not a PNG."""
    path = tmp_path / "notpng.txt"
    path.write_text("hello world")

    with pytest.raises(ValueError, match="not a PNG"):
        read_png(path)


def test_read_png_no_ihdr(tmp_path: Path) -> None:
    """Read PNG with missing IHDR."""
    path = tmp_path / "noihdr.png"
    data = bytearray(PNG_SIGNATURE)
    data.extend(struct.pack(">I", 0))
    data.extend(b"IEND")
    data.extend(struct.pack(">I", _crc(b"IEND")))

    path.write_bytes(bytes(data))

    with pytest.raises(ValueError, match="no IHDR"):
        read_png(path)


def test_read_png_unsupported_depth(tmp_path: Path) -> None:
    """Read PNG with unsupported bit depth."""
    ihdr = struct.pack(">IIBBBBB", 2, 2, 16, 2, 0, 0, 0)  # 16-bit depth

    path = tmp_path / "depth16.png"
    _write_png_chunks(path, [(b"IHDR", ihdr), (b"IEND", b"")])

    with pytest.raises(ValueError, match="8-bit"):
        read_png(path)


def test_read_png_unsupported_color_type(tmp_path: Path) -> None:
    """Read PNG with unsupported color type."""
    ihdr = struct.pack(">IIBBBBB", 2, 2, 8, 3, 0, 0, 0)  # Indexed color

    path = tmp_path / "indexed.png"
    _write_png_chunks(path, [(b"IHDR", ihdr), (b"IEND", b"")])

    with pytest.raises(ValueError, match="RGB|RGBA|grayscale"):
        read_png(path)


def test_read_png_interlaced(tmp_path: Path) -> None:
    """Read interlaced PNG (unsupported)."""
    ihdr = struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 1)  # Interlaced

    path = tmp_path / "interlaced.png"
    _write_png_chunks(path, [(b"IHDR", ihdr), (b"IEND", b"")])

    with pytest.raises(ValueError, match="non-interlaced"):
        read_png(path)


def test_write_and_read_roundtrip(tmp_path: Path) -> None:
    """Write PNG and read it back."""
    width, height = 40, 30
    rgb = bytes([(x * y) & 0xff for x in range(width) for y in range(height) for _ in range(3)])

    path = tmp_path / "roundtrip.png"
    write_png(path, width, height, rgb)

    w, h, data = read_png(path)
    assert (w, h) == (width, height)
    assert data == rgb


def test_write_png_wrong_size(tmp_path: Path) -> None:
    """Write PNG with mismatched data size."""
    path = tmp_path / "badsize.png"
    rgb = bytes([0] * 100)  # Wrong size for 10x10x3

    with pytest.raises(ValueError, match="size"):
        write_png(path, 10, 10, rgb)


def test_write_png_large(tmp_path: Path) -> None:
    """Write and read back a larger image (performance sanity check)."""
    width, height = 400, 300
    # Create a simple pattern
    rgb = bytearray()
    for y in range(height):
        for x in range(width):
            r = (x * 256 // width) & 0xff
            g = (y * 256 // height) & 0xff
            b = ((x + y) * 256 // (width + height)) & 0xff
            rgb.extend([r, g, b])

    path = tmp_path / "large.png"
    write_png(path, width, height, bytes(rgb))

    w, h, data = read_png(path)
    assert (w, h) == (width, height)
    assert data == bytes(rgb)


def test_truncated_png(tmp_path: Path) -> None:
    """Read truncated PNG (missing data)."""
    width, height = 2, 2
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)

    path = tmp_path / "truncated.png"
    data = bytearray(PNG_SIGNATURE)
    data.extend(struct.pack(">I", 13))
    data.extend(b"IHDR")
    data.extend(ihdr)
    data.extend(struct.pack(">I", _crc(b"IHDR" + ihdr)))
    # Missing IDAT, just write partial chunk header

    path.write_bytes(bytes(data))

    with pytest.raises(ValueError):
        read_png(path)
