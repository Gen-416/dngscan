# SPDX-License-Identifier: GPL-3.0-or-later
"""Chromatic look layer applied on top of the AgX render, in Oklab.

Parameters are MEASURED geometry (facts), not copied LUT data: tools/extract_arri_look.py
feeds a synthetic hue×L×C sweep through locally downloaded official ARRI display LUTs and
dngscan AgX, then records the Oklab delta. No ARRI LUT ships with this repository.
Tone stays with AgX; this layer is purely chromatic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None  # type: ignore[assignment]

LOOK_CHOICES = ("none", "classic", "reveal")


@dataclass(frozen=True)
class LookField:
    """Measured chromatic field relative to dngscan AgX (TypicalPlan reference)."""

    hue_rotation_deg: tuple[float, ...]  # 12 sectors, Oklab hue
    chroma_ratio: tuple[float, ...]  # per-sector C ratio at mid-L
    mid_chroma_ratio: float
    shadow_chroma_ratio: float
    highlight_chroma_ratio: float
    shadow_cool_a: float = 0.0
    shadow_cool_b: float = 0.0
    shadow_l_lo: float = 0.10
    shadow_l_hi: float = 0.35
    highlight_l_lo: float = 0.75
    highlight_l_hi: float = 0.92
    sat_knee_c: float = 0.18
    sat_knee_relief: float = 1.0  # >1 = less chroma trim above knee (soft rolloff)
    skin_hue_lo: float = 20.0
    skin_hue_hi: float = 60.0
    skin_hue_center: float = 40.0
    skin_hue_pull: float = 0.0  # fraction of (center-hue) arc to close
    skin_chroma_scale: float = 1.0  # extra chroma trim in skin band vs mid


# Populated by tools/extract_arri_look.py --emit; re-run that script to refresh from local LUTs.
LOOK_FIELDS: dict[str, LookField] = {
    "classic": LookField(
        hue_rotation_deg=(-2.12, -3.32, 0.57, 4.12, 3.11, -0.0, -0.89, 0.84, 4.71, 6.06, 3.26, 0.07),
        chroma_ratio=(0.874, 0.787, 0.78, 0.812, 0.858, 0.862, 0.831, 0.795, 0.816, 0.902, 0.95, 0.936),
        mid_chroma_ratio=0.851,
        shadow_chroma_ratio=0.739,
        highlight_chroma_ratio=0.887,
        shadow_cool_a=0.0002,
        shadow_cool_b=-0.0001,
        shadow_l_lo=0.10,
        shadow_l_hi=0.20,
        highlight_l_lo=0.75,
        highlight_l_hi=0.92,
        sat_knee_c=0.20,
        sat_knee_relief=1.046,
        skin_hue_lo=20.0,
        skin_hue_hi=60.0,
        skin_hue_center=40.0,
        skin_hue_pull=0.041,
        skin_chroma_scale=0.959,
    ),
    "reveal": LookField(
        hue_rotation_deg=(-3.48, -3.26, 2.2, 6.49, 5.32, 0.92, 0.05, 1.97, 4.57, 4.88, 2.69, -0.4),
        chroma_ratio=(0.837, 0.76, 0.743, 0.787, 0.853, 0.844, 0.787, 0.688, 0.776, 0.864, 0.896, 0.885),
        mid_chroma_ratio=0.835,
        shadow_chroma_ratio=0.533,
        highlight_chroma_ratio=0.738,
        shadow_cool_a=-0.0007,
        shadow_cool_b=-0.0021,
        shadow_l_lo=0.10,
        shadow_l_hi=0.29,
        highlight_l_lo=0.75,
        highlight_l_hi=0.92,
        sat_knee_c=0.20,
        sat_knee_relief=1.006,
        skin_hue_lo=20.0,
        skin_hue_hi=60.0,
        skin_hue_center=40.0,
        skin_hue_pull=0.001,
        skin_chroma_scale=0.955,
    ),
}


def _smoothstep(edge0: float, edge1: float, x: Any) -> Any:
    t = np.clip((x - edge0) / max(edge1 - edge0, 1e-9), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _periodic_interp(table: tuple[float, ...], hue_deg: Any) -> Any:
    """Circular linear interpolation of a 12-sector table over hue."""
    n = len(table)
    vals = np.asarray(table + (table[0],), dtype=np.float32)
    pos = (hue_deg - 15.0) % 360.0 / 30.0
    pos = np.clip(pos, 0.0, float(n) - 1e-5)
    idx = np.floor(pos).astype(np.int32)
    frac = (pos - idx).astype(np.float32)
    return vals[idx] * (1.0 - frac) + vals[idx + 1] * frac


def _hue_in_arc(hue_deg: Any, lo: float, hi: float) -> Any:
    """Weight 1 inside the hue arc [lo, hi] on the circle, 0 outside."""
    h = hue_deg % 360.0
    if lo <= hi:
        inside = (h >= lo) & (h <= hi)
    else:
        inside = (h >= lo) | (h <= hi)
    edge = np.minimum(np.abs(h - lo), np.abs(h - hi))
    edge = np.minimum(edge, 360.0 - edge)
    return inside.astype(np.float32) * _smoothstep(6.0, 0.0, edge)


def apply_look_oklab(lab_l: Any, lab_a: Any, lab_b: Any, look: str, strength: float = 1.0) -> tuple[Any, Any, Any]:
    """Apply the measured chromatic field on Oklab coordinates.

    L is untouched. Four operator families:
    1) sector hue rotation (e.g. green toward cyan),
    2) L-dependent chroma trim (shadow / highlight ramps),
    3) high-saturation soft knee (extra relief above sat_knee_c),
    4) skin-band hue convergence + chroma damp.
    """
    field = LOOK_FIELDS[look]
    s = np.float32(max(0.0, strength))
    chroma = np.hypot(lab_a, lab_b)
    hue = np.degrees(np.arctan2(lab_b, lab_a)) % 360.0

    chroma_w = _smoothstep(0.005, 0.03, chroma)
    rot = np.radians(_periodic_interp(field.hue_rotation_deg, hue)) * s * chroma_w
    cos_r = np.cos(rot)
    sin_r = np.sin(rot)
    a2 = lab_a * cos_r - lab_b * sin_r
    b2 = lab_a * sin_r + lab_b * cos_r
    hue = np.degrees(np.arctan2(b2, a2)) % 360.0

    skin_w = _hue_in_arc(hue, field.skin_hue_lo, field.skin_hue_hi) * chroma_w
    if field.skin_hue_pull > 0.0:
        delta = (field.skin_hue_center - hue + 180.0) % 360.0 - 180.0
        pull = np.radians(delta) * np.float32(field.skin_hue_pull) * s * skin_w
        cos_p = np.cos(pull)
        sin_p = np.sin(pull)
        a3 = a2 * cos_p - b2 * sin_p
        b3 = a2 * sin_p + b2 * cos_p
        a2, b2 = a3, b3

    scale = _periodic_interp(field.chroma_ratio, hue).astype(np.float32)
    shadow_extra = field.shadow_chroma_ratio / field.mid_chroma_ratio
    highlight_extra = field.highlight_chroma_ratio / field.mid_chroma_ratio
    scale = scale * (1.0 + (shadow_extra - 1.0) * _smoothstep(field.shadow_l_hi, field.shadow_l_lo, lab_l))
    scale = scale * (1.0 + (highlight_extra - 1.0) * _smoothstep(field.highlight_l_lo, field.highlight_l_hi, lab_l))
    if field.sat_knee_relief != 1.0:
        knee_w = _smoothstep(field.sat_knee_c, field.sat_knee_c + 0.08, chroma)
        scale = scale * (1.0 + (np.float32(field.sat_knee_relief) - 1.0) * knee_w)
    if field.skin_chroma_scale != 1.0:
        scale = scale * (1.0 + (np.float32(field.skin_chroma_scale) - 1.0) * skin_w)
    scale = 1.0 + (scale - 1.0) * s
    a2 = a2 * scale
    b2 = b2 * scale

    cool_w = s * _smoothstep(field.shadow_l_hi, field.shadow_l_lo, lab_l) * (1.0 - chroma_w)
    if field.shadow_cool_a != 0.0:
        a2 = a2 + np.float32(field.shadow_cool_a) * cool_w
    if field.shadow_cool_b != 0.0:
        b2 = b2 + np.float32(field.shadow_cool_b) * cool_w

    return lab_l, a2, b2
