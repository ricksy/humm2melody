"""Generate the app icons.

Drawn rather than sourced so there is no binary blob in the tree whose origin
nobody remembers, and so the marque can be regenerated at any size. The shape
is the piano roll: four bars climbing left to right, which is what the app
shows you and what distinguishes it from every other microphone icon.

    uv run web/scripts/make-icons.py
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parents[1] / "public" / "icons"

BG = (0x14, 0x14, 0x17)
BARS = [(0x7D, 0xD3, 0xFC), (0x81, 0x8C, 0xF8), (0x7D, 0xD3, 0xFC), (0xFB, 0xBF, 0x24)]

# start, end, as fractions of the width — a rising phrase, with the last note
# held longer, so the shape reads as music rather than as a bar chart.
SPANS = [(0.10, 0.42), (0.26, 0.58), (0.42, 0.74), (0.58, 0.94)]


def write_png(path: Path, rgb: np.ndarray) -> None:
    """Minimal RGB PNG writer — avoids a Pillow dependency for four files."""
    height, width, _ = rgb.shape
    raw = b"".join(b"\x00" + rgb[y].tobytes() for y in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def draw(size: int, inset: float = 0.0) -> np.ndarray:
    """`inset` shrinks the artwork for maskable icons, whose outer ring is
    cropped to whatever shape the launcher prefers."""
    img = np.zeros((size, size, 3), dtype=np.uint8)
    img[:, :] = BG

    scale = 1.0 - 2 * inset
    bar_h = max(2, int(size * 0.105 * scale))
    gap = size * 0.155 * scale
    top = size * (inset + 0.16 * scale)

    for i, ((x0, x1), colour) in enumerate(zip(SPANS, BARS)):
        y = int(top + (3 - i) * gap)
        left = int(size * (inset + x0 * scale))
        right = int(size * (inset + x1 * scale))
        img[y : y + bar_h, left:right] = colour

    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, size, inset in [
        ("icon-192.png", 192, 0.0),
        ("icon-512.png", 512, 0.0),
        # Maskable icons are cropped to the launcher's shape; keeping the
        # artwork inside the middle 60% survives even an aggressive circle.
        ("icon-maskable-512.png", 512, 0.2),
        # iOS ignores the manifest icons for the home screen.
        ("apple-touch-icon.png", 180, 0.06),
    ]:
        write_png(OUT / name, draw(size, inset))
        print(f"  {name:26} {size}×{size}")


if __name__ == "__main__":
    main()
