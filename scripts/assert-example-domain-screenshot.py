#!/usr/bin/env python3
"""Reject product screenshots where Example Domain did not visibly render."""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path


def paeth(a: int, b: int, c: int) -> int:
    estimate = a + b - c
    pa = abs(estimate - a)
    pb = abs(estimate - b)
    pc = abs(estimate - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def read_rgb(path: Path) -> tuple[int, int, list[bytes], int]:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")

    offset = 8
    width = height = bit_depth = color_type = interlace = None
    compressed = bytearray()
    while offset < len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        kind = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if kind == b"IHDR":
            width, height, bit_depth, color_type, _, _, interlace = struct.unpack(
                ">IIBBBBB", payload
            )
        elif kind == b"IDAT":
            compressed.extend(payload)
        elif kind == b"IEND":
            break

    if None in (width, height, bit_depth, color_type, interlace):
        raise ValueError("missing PNG header")
    if bit_depth != 8 or color_type not in (2, 6) or interlace != 0:
        raise ValueError(
            f"unsupported PNG format: depth={bit_depth} color={color_type} interlace={interlace}"
        )

    channels = 3 if color_type == 2 else 4
    stride = width * channels
    raw = zlib.decompress(bytes(compressed))
    expected = height * (stride + 1)
    if len(raw) != expected:
        raise ValueError(f"unexpected PNG payload: {len(raw)} != {expected}")

    rows: list[bytes] = []
    previous = bytearray(stride)
    cursor = 0
    for _ in range(height):
        filter_type = raw[cursor]
        cursor += 1
        encoded = raw[cursor : cursor + stride]
        cursor += stride
        decoded = bytearray(stride)
        for x, value in enumerate(encoded):
            left = decoded[x - channels] if x >= channels else 0
            up = previous[x]
            upper_left = previous[x - channels] if x >= channels else 0
            if filter_type == 0:
                predictor = 0
            elif filter_type == 1:
                predictor = left
            elif filter_type == 2:
                predictor = up
            elif filter_type == 3:
                predictor = (left + up) // 2
            elif filter_type == 4:
                predictor = paeth(left, up, upper_left)
            else:
                raise ValueError(f"unsupported PNG filter {filter_type}")
            decoded[x] = (value + predictor) & 0xFF
        rows.append(bytes(decoded))
        previous = decoded
    return width, height, rows, channels


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: assert-example-domain-screenshot.py SCREENSHOT.png")
    width, height, rows, channels = read_rgb(Path(sys.argv[1]))
    if height <= 72:
        raise SystemExit(f"screenshot is too short for a page region: {width}x{height}")

    unique: set[tuple[int, int, int]] = set()
    dark = 0
    link_blue = 0
    for row in rows[72:]:
        for offset in range(0, len(row), channels):
            r, g, b = row[offset : offset + 3]
            unique.add((r, g, b))
            dark += r < 100 and g < 100 and b < 100
            link_blue += b > 100 and b > r + 35 and b > g + 20

    print(
        f"external_page_pixels size={width}x{height} unique={len(unique)} "
        f"dark={dark} link_blue={link_blue}"
    )
    if len(unique) < 100 or dark < 500 or link_blue < 20:
        raise SystemExit("external page is blank or lacks visible Example Domain content")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
