"""PNG reading and writing using only the standard library.

WHY: The screenshot harness must work without image dependencies. This module
decodes PNGs (8-bit RGB/RGBA, non-interlaced) and encodes them, handling all
five PNG filter types efficiently and validating CRC checksums.

Typical use: read_png() for testing, write_png() for diff visualization.
"""

from __future__ import annotations

import struct
import zlib
from itertools import accumulate
from pathlib import Path


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
CRC_TABLE = [0] * 256
for n in range(256):
    c = n
    for _ in range(8):
        c = (c >> 1) ^ 0xedb88320 if c & 1 else c >> 1
    CRC_TABLE[n] = c


def _crc(data: bytes) -> int:
    """Compute CRC32 for PNG chunk (excluding the 4-byte CRC itself)."""
    c = 0xffffffff
    for b in data:
        c = CRC_TABLE[(c ^ b) & 0xff] ^ (c >> 8)
    return c ^ 0xffffffff


def read_png(path: Path) -> tuple[int, int, bytes]:
    """
    Decode a PNG file into raw 8-bit RGB pixels (alpha dropped if RGBA).

    Args:
        path: PNG file, 8 bits per channel, colour type 2 (RGB) or 6 (RGBA),
            or 0 (grayscale), not interlaced.

    Returns:
        (width, height, pixel_data) where pixel_data is bytes of 8-bit RGB
        values concatenated (no filter bytes, grayscale expanded to RGB).

    Raises:
        ValueError: if the file is not a valid PNG of a supported kind.
    """
    data = path.read_bytes()
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("not a PNG file")

    pos, idat_chunks, header = len(PNG_SIGNATURE), [], None
    while pos < len(data):
        if pos + 8 > len(data):
            raise ValueError("truncated PNG chunk header")

        length, chunk_type = struct.unpack(">I4s", data[pos : pos + 8])
        if pos + 8 + length + 4 > len(data):
            raise ValueError("truncated PNG chunk data")

        chunk_data = data[pos + 8 : pos + 8 + length]
        chunk_crc = struct.unpack(">I", data[pos + 8 + length : pos + 12 + length])[0]

        # WHY: Validate CRC to catch corrupted files early
        expected_crc = _crc(chunk_type + chunk_data)
        if chunk_crc != expected_crc:
            raise ValueError(f"CRC mismatch in {chunk_type.decode('ascii', errors='replace')} chunk")

        pos += 12 + length

        if chunk_type == b"IHDR":
            if len(chunk_data) != 13:
                raise ValueError("invalid IHDR length")
            header = struct.unpack(">IIBBBBB", chunk_data)
        elif chunk_type == b"IDAT":
            idat_chunks.append(chunk_data)
        elif chunk_type == b"IEND":
            break

    if header is None:
        raise ValueError("no IHDR chunk found")

    width, height, depth, color_type, compression, filter_method, interlace = header
    if depth != 8:
        raise ValueError("only 8-bit depth is supported")
    if color_type not in (0, 2, 6):
        raise ValueError("only RGB, RGBA and grayscale are supported")
    if compression != 0:
        raise ValueError("only compression method 0 is supported")
    if filter_method != 0:
        raise ValueError("only filter method 0 is supported")
    if interlace != 0:
        raise ValueError("only non-interlaced images are supported")

    # Decode color type: 0=grayscale (1 bpp), 2=RGB (3 bpp), 6=RGBA (4 bpp)
    bytes_per_pixel = {0: 1, 2: 3, 6: 4}[color_type]

    # Decompress and unfilter
    try:
        raw = zlib.decompress(b"".join(idat_chunks))
    except zlib.error as exc:
        raise ValueError(f"decompression error: {exc}") from exc
    unfiltered = _unfilter(raw, width, height, bytes_per_pixel)

    # Drop alpha if RGBA, expand grayscale to RGB
    if color_type == 6:  # RGBA -> RGB
        rgb = bytearray(width * height * 3)
        for i in range(width * height):
            rgb[i * 3 : i * 3 + 3] = unfiltered[i * 4 : i * 4 + 3]
        return width, height, bytes(rgb)
    elif color_type == 0:  # Grayscale -> RGB (replicate to all channels)
        rgb = bytearray(width * height * 3)
        for i in range(width * height):
            g = unfiltered[i]
            rgb[i * 3 : i * 3 + 3] = bytes([g, g, g])
        return width, height, bytes(rgb)
    else:  # RGB, already correct format
        return width, height, unfiltered


def _unfilter(raw: bytes, width: int, height: int, bpp: int) -> bytes:
    """
    Undo the per-row PNG filters (None, Sub, Up, Average, Paeth).

    Args:
        raw: Decompressed IDAT data (one filter-type byte plus one row per line).
        width: Image width in pixels.
        height: Image height in pixels.
        bpp: Bytes per pixel.

    Returns:
        The unfiltered pixel rows, concatenated.

    Raises:
        ValueError: on unknown filter type or truncated data.
    """
    stride = width * bpp
    expected_len = height * (stride + 1)
    if len(raw) != expected_len:
        raise ValueError(f"image data size mismatch: expected {expected_len}, got {len(raw)}")

    out = bytearray(height * stride)
    prev_row = bytearray(stride)
    pos = 0

    for y in range(height):
        filter_type = raw[pos]
        line = bytearray(raw[pos + 1 : pos + 1 + stride])
        pos += 1 + stride

        if filter_type == 0:  # None: no filtering
            pass
        elif filter_type == 1:  # Sub: add left neighbor
            for c in range(bpp):
                line[c::bpp] = bytes(accumulate(line[c::bpp], lambda a, b: (a + b) & 255))
        elif filter_type == 2:  # Up: add pixel above
            line = bytearray((a + b) & 255 for a, b in zip(line, prev_row))
        elif filter_type == 3:  # Average: add average of left and above
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                above = prev_row[i]
                line[i] = (line[i] + ((left + above) >> 1)) & 255
        elif filter_type == 4:  # Paeth: add Paeth predictor
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev_row[i]
                c = prev_row[i - bpp] if i >= bpp else 0
                # Paeth predictor: pick closest of a, b, c
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pred) & 255
        else:
            raise ValueError(f"unknown PNG filter type {filter_type}")

        out[y * stride : (y + 1) * stride] = line
        prev_row = line

    return bytes(out)


def write_png(path: Path, width: int, height: int, rgb: bytes) -> None:
    """
    Write an 8-bit RGB image as a PNG file.

    Args:
        path: Output file path.
        width: Image width in pixels.
        height: Image height in pixels.
        rgb: Pixel data as bytes (RGB triplets, concatenated).

    Raises:
        ValueError: if the data size doesn't match width*height*3.
    """
    if len(rgb) != width * height * 3:
        raise ValueError(f"rgb data size {len(rgb)} != {width * height * 3}")

    # WHY: Filter type 0 (None) is simplest and still compresses well with zlib.
    # No per-pixel filtering overhead, and modern images are already quite uniform.
    stride = width * 3
    idat_raw = bytearray()
    for y in range(height):
        idat_raw.append(0)  # filter type: None
        idat_raw.extend(rgb[y * stride : (y + 1) * stride])

    # Compress with zlib level 6 (good balance between speed and compression)
    idat_data = zlib.compress(bytes(idat_raw), level=6)

    # Build PNG file
    png_data = bytearray(PNG_SIGNATURE)

    # IHDR chunk: width, height, 8 bits, RGB (color type 2), compression 0, filter 0, no interlace
    ihdr_body = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png_data.extend(struct.pack(">I", 13))
    png_data.extend(b"IHDR")
    png_data.extend(ihdr_body)
    png_data.extend(struct.pack(">I", _crc(b"IHDR" + ihdr_body)))

    # IDAT chunk
    png_data.extend(struct.pack(">I", len(idat_data)))
    png_data.extend(b"IDAT")
    png_data.extend(idat_data)
    png_data.extend(struct.pack(">I", _crc(b"IDAT" + idat_data)))

    # IEND chunk
    png_data.extend(struct.pack(">I", 0))
    png_data.extend(b"IEND")
    png_data.extend(struct.pack(">I", _crc(b"IEND")))

    path.write_bytes(bytes(png_data))
