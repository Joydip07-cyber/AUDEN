"""Packs the PNG icons produced by build\\make_icon.ps1 into assets\\auden.ico."""
from __future__ import annotations

import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
SIZES = [256, 128, 64, 48, 32, 16]

images = []
for size in SIZES:
    data = (ASSETS / f"icon-{size}.png").read_bytes()
    images.append((size, data))

header = struct.pack("<HHH", 0, 1, len(images))
offset = 6 + 16 * len(images)
entries = b""
for size, data in images:
    dim = 0 if size >= 256 else size
    entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
    offset += len(data)

(ASSETS / "auden.ico").write_bytes(header + entries + b"".join(data for _, data in images))
print(f"Wrote {ASSETS / 'auden.ico'}")
