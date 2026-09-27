#!/usr/bin/env python3
"""
Compare two PNG screenshots pixel by pixel using only the standard library.

WHY not a byte compare of the files: two PNGs with the same pixels can differ in
their compressed bytes. This tool decodes both images (8-bit RGB or RGBA, no
interlacing - what QEMU's screendump writes), compares the pixels and reports how
many differ and WHERE, so that a difference can be traced to its cause (clock,
cursor, animation).

Usage: compare_png.py A.png B.png [--grid 16x9]
Exit status: 0 = identical pixels, 1 = differences, 2 = bad input.
"""

from __future__ import annotations

import argparse
import struct
import sys
import zlib
from itertools import accumulate
from pathlib import Path

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def decode_png(path: Path) -> tuple[int, int, int, bytes]:
    """
    Decode a PNG file into raw pixel rows.

    Args:
        path: PNG file, 8 bits per channel, colour type 2 (RGB) or 6 (RGBA),
            not interlaced.

    Returns:
        (width, height, bytes per pixel, pixel data without filter bytes).

    Raises:
        ValueError: if the file is not a PNG of a supported kind.
    """
    data = path.read_bytes()
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError(f"{path.name}: not a PNG file")
    pos, idat, header = len(PNG_SIGNATURE), [], None
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length  # length + type + body + crc
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            idat.append(body)
        elif kind == b"IEND":
            break
    if header is None:
        raise ValueError(f"{path.name}: no IHDR chunk")
    width, height, depth, color, _, _, interlace = header
    if depth != 8 or color not in (2, 6) or interlace != 0:
        raise ValueError(f"{path.name}: only 8-bit RGB/RGBA without interlacing is supported")
    bpp = 3 if color == 2 else 4
    return width, height, bpp, unfilter(zlib.decompress(b"".join(idat)), width, height, bpp)


def unfilter(raw: bytes, width: int, height: int, bpp: int) -> bytes:
    """
    Undo the per-row PNG filters (None, Sub, Up, Average, Paeth).

    Args:
        raw: Decompressed IDAT data: one filter-type byte plus one row per line.
        width: Image width in pixels.
        height: Image height in pixels.
        bpp: Bytes per pixel.

    Returns:
        The unfiltered pixel rows, concatenated.

    Raises:
        ValueError: on an unknown filter type or truncated data.
    """
    stride = width * bpp
    if len(raw) != height * (stride + 1):
        raise ValueError("unexpected amount of image data")
    out = bytearray(height * stride)
    prev = bytearray(stride)
    pos = 0
    for y in range(height):
        kind = raw[pos]
        line = bytearray(raw[pos + 1:pos + 1 + stride])
        pos += 1 + stride
        if kind == 1:  # Sub: add the pixel to the left; one running sum per channel
            for c in range(bpp):
                line[c::bpp] = bytes(accumulate(line[c::bpp], lambda a, b: (a + b) & 255))
        elif kind == 2:  # Up: add the pixel above
            line = bytearray((a + b) & 255 for a, b in zip(line, prev))
        elif kind == 3:  # Average of left and above
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 255
        elif kind == 4:  # Paeth predictor
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pred) & 255
        elif kind != 0:
            raise ValueError(f"unknown PNG filter type {kind}")
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return bytes(out)


def compare(a: Path, b: Path, grid: tuple[int, int]) -> dict:
    """
    Compare two images.

    Args:
        a: First PNG.
        b: Second PNG.
        grid: (columns, rows) of the coarse map that shows where differences are.

    Returns:
        A dict with the sizes, the number and fraction of differing pixels, the
        bounding box of all differences, the largest channel difference and the
        per-tile difference counts of the coarse grid.

    Raises:
        ValueError: if an image cannot be decoded or the sizes differ.
    """
    wa, ha, bppa, pa = decode_png(a)
    wb, hb, bppb, pb = decode_png(b)
    if (wa, ha, bppa) != (wb, hb, bppb):
        raise ValueError(f"image formats differ: {wa}x{ha}x{bppa} vs {wb}x{hb}x{bppb}")
    stride = wa * bppa
    cols, rows = grid
    tiles: dict[tuple[int, int], int] = {}
    diff_pixels = 0
    max_delta = 0
    x_min, y_min, x_max, y_max = wa, ha, -1, -1
    for y in range(ha):
        row_a = pa[y * stride:(y + 1) * stride]
        row_b = pb[y * stride:(y + 1) * stride]
        if row_a == row_b:
            continue  # fast path: most rows are untouched
        for x in range(wa):
            i = x * bppa
            if row_a[i:i + bppa] != row_b[i:i + bppa]:
                diff_pixels += 1
                max_delta = max(max_delta, max(abs(row_a[i + k] - row_b[i + k]) for k in range(bppa)))
                x_min, x_max = min(x_min, x), max(x_max, x)
                y_min, y_max = min(y_min, y), max(y_max, y)
                key = (x * cols // wa, y * rows // ha)
                tiles[key] = tiles.get(key, 0) + 1
    total = wa * ha
    return {
        "size": f"{wa}x{ha}",
        "total_pixels": total,
        "differing_pixels": diff_pixels,
        "differing_fraction": diff_pixels / total,
        "bounding_box_xyxy": None if diff_pixels == 0 else [x_min, y_min, x_max, y_max],
        "max_channel_delta": max_delta,
        "tiles_col_row_count": sorted(((c, r, n) for (c, r), n in tiles.items()), key=lambda t: -t[2]),
    }


def main() -> int:
    """Command line entry point; prints a short human-readable report."""
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("a", type=Path)
    p.add_argument("b", type=Path)
    p.add_argument("--grid", default="16x9", help="COLSxROWS of the difference map")
    args = p.parse_args()
    try:
        cols, rows = (int(v) for v in args.grid.split("x"))
        if not (1 <= cols <= 200 and 1 <= rows <= 200):
            raise ValueError("grid out of range")
        result = compare(args.a, args.b, (cols, rows))
    except (ValueError, OSError, zlib.error) as exc:
        print(f"compare_png.py: error: {exc}", file=sys.stderr)
        return 2
    print(f"size                : {result['size']}")
    print(f"differing pixels    : {result['differing_pixels']} of {result['total_pixels']} "
          f"({100 * result['differing_fraction']:.6f} %)")
    print(f"bounding box (xyxy) : {result['bounding_box_xyxy']}")
    print(f"max channel delta   : {result['max_channel_delta']}")
    if result["tiles_col_row_count"]:
        print(f"tiles ({cols}x{rows} grid, col,row: pixels), largest first:")
        for col, row, count in result["tiles_col_row_count"][:12]:
            print(f"  ({col:2d},{row:2d}): {count}")
    return 0 if result["differing_pixels"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
