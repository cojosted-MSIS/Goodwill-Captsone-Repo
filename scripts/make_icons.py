"""Draw the web app's icons: python scripts/make_icons.py

A white note on the theme's teal, written as PNGs with the standard library only. The note sits
inside the middle 60 percent, so the icon also works where a phone crops it to a circle.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "ui" / "web" / "icons"
TEAL, WHITE = (0x0F, 0x5C, 0x57), (0xFF, 0xFF, 0xFF)


def pixel(x: float, y: float) -> tuple[int, int, int]:
    """The color at (x, y), both from 0 to 1."""
    if not (0.31 <= x <= 0.69 and 0.25 <= y <= 0.75):
        return TEAL
    lines = (0.36, 0.46, 0.56) if x <= 0.62 else (0.36, 0.46)
    if 0.38 <= x <= 0.62 and any(line <= y <= line + 0.045 for line in lines):
        return TEAL
    return WHITE


def png(size: int) -> bytes:
    rows = b"".join(b"\x00" + bytes(c for x in range(size) for c in pixel((x + 0.5) / size, (y + 0.5) / size)) for y in range(size))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b"")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for size in (192, 512):
        (OUT / f"icon-{size}.png").write_bytes(png(size))
        print(f"icon-{size}.png")
