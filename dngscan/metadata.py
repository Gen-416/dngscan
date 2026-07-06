# SPDX-License-Identifier: GPL-3.0-or-later
"""Minimal TIFF/DNG tag reader for camera identification and shot metadata.

Reads only what the priors layer needs (Make, Model, ISO, AsShotNeutral) with
targeted seeks — no external dependency, no full-file load. Returns None fields
on any parse trouble; callers must treat everything as best-effort.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

TAG_MAKE = 271
TAG_MODEL = 272
TAG_EXIF_IFD = 34665
TAG_ISO = 34855
TAG_AS_SHOT_NEUTRAL = 50728

_TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8}


@dataclass
class DngShotInfo:
    make: str | None = None
    model: str | None = None
    iso: int | None = None
    as_shot_neutral: tuple[float, float, float] | None = None


def _read_ifd_entries(fh, offset: int, endian: str) -> list[tuple[int, int, int, bytes]]:
    fh.seek(offset)
    count_raw = fh.read(2)
    if len(count_raw) < 2:
        return []
    (count,) = struct.unpack(endian + "H", count_raw)
    if count > 4096:
        return []
    data = fh.read(count * 12)
    entries = []
    for i in range(count):
        tag, typ, num = struct.unpack(endian + "HHL", data[i * 12 : i * 12 + 8])
        entries.append((tag, typ, num, data[i * 12 + 8 : i * 12 + 12]))
    return entries


def _entry_values(fh, typ: int, num: int, raw: bytes, endian: str) -> list:
    size = _TYPE_SIZES.get(typ)
    if size is None:
        return []
    total = size * num
    if total <= 4:
        buf = raw[:total]
    else:
        (off,) = struct.unpack(endian + "L", raw)
        fh.seek(off)
        buf = fh.read(total)
        if len(buf) < total:
            return []
    if typ == 2:  # ASCII
        return [buf.split(b"\x00")[0].decode("ascii", errors="replace").strip()]
    fmt = {1: "B", 3: "H", 4: "L", 8: "h", 9: "l", 11: "f", 12: "d"}.get(typ)
    if fmt:
        return list(struct.unpack(endian + fmt * num, buf))
    if typ in (5, 10):  # RATIONAL / SRATIONAL
        sub = "l" if typ == 10 else "L"
        parts = struct.unpack(endian + sub * (2 * num), buf)
        return [parts[2 * i] / parts[2 * i + 1] if parts[2 * i + 1] else 0.0 for i in range(num)]
    return []


def read_dng_shot_info(path: Path) -> DngShotInfo:
    info = DngShotInfo()
    try:
        with open(path, "rb") as fh:
            head = fh.read(8)
            if len(head) < 8 or head[:2] not in (b"II", b"MM"):
                return info
            endian = "<" if head[:2] == b"II" else ">"
            (magic,) = struct.unpack(endian + "H", head[2:4])
            if magic != 42:
                return info
            (ifd0_off,) = struct.unpack(endian + "L", head[4:8])
            exif_off = None
            for tag, typ, num, raw in _read_ifd_entries(fh, ifd0_off, endian):
                if tag == TAG_MAKE:
                    vals = _entry_values(fh, typ, num, raw, endian)
                    info.make = vals[0] if vals else None
                elif tag == TAG_MODEL:
                    vals = _entry_values(fh, typ, num, raw, endian)
                    info.model = vals[0] if vals else None
                elif tag == TAG_ISO and info.iso is None:
                    vals = _entry_values(fh, typ, num, raw, endian)
                    info.iso = int(vals[0]) if vals else None
                elif tag == TAG_EXIF_IFD:
                    vals = _entry_values(fh, typ, num, raw, endian)
                    exif_off = int(vals[0]) if vals else None
                elif tag == TAG_AS_SHOT_NEUTRAL:
                    vals = _entry_values(fh, typ, num, raw, endian)
                    if len(vals) >= 3:
                        info.as_shot_neutral = (float(vals[0]), float(vals[1]), float(vals[2]))
            if info.iso is None and exif_off:
                for tag, typ, num, raw in _read_ifd_entries(fh, exif_off, endian):
                    if tag == TAG_ISO:
                        vals = _entry_values(fh, typ, num, raw, endian)
                        info.iso = int(vals[0]) if vals else None
                        break
    except (OSError, struct.error):
        pass
    return info
