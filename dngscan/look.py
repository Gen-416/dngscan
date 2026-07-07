# SPDX-License-Identifier: GPL-3.0-or-later
"""Chromatic look layer applied on top of the AgX render, in Oklab.

Parameters are MEASURED geometry (facts), not copied LUT data: tools/extract_arri_look.py
feeds a synthetic hue×L×C sweep through locally downloaded official ARRI display LUTs and
dngscan AgX, then records the Oklab delta. No ARRI LUT ships with this repository.
Tone stays with AgX; this layer is purely chromatic.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, fields as dataclass_fields
from pathlib import Path
from typing import Any

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None  # type: ignore[assignment]

# User-extendable look registry: fields measured from locally downloaded official LUTs
# are appended here by `tools/extract_arri_look.py --append-json` — adding a new look
# never requires editing code. The file lives next to the other local-only assets.
LOOK_FIELDS_JSON = Path(__file__).resolve().parents[1] / "dngscan_assets" / "look_fields.json"


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
    skin_warm_a: float = 0.0
    skin_warm_b: float = 0.0
    neutral_cool_a: float = 0.0
    neutral_cool_b: float = 0.0
    neutral_cool_l_lo: float = 0.16
    neutral_cool_l_hi: float = 0.68
    neutral_cool_l_falloff: float = 0.92
    neutral_cool_chroma_hi: float = 0.075
    highlight_warm_a: float = 0.0
    highlight_warm_b: float = 0.0
    highlight_warm_l_lo: float = 0.58
    highlight_warm_l_hi: float = 0.92
    highlight_warm_chroma_hi: float = 0.12
    magenta_hue_lo: float = 300.0
    magenta_hue_hi: float = 18.0
    magenta_hue_center: float = 8.0
    magenta_hue_pull: float = 0.0
    magenta_chroma_scale: float = 1.0


# Populated by tools/extract_arri_look.py --emit; re-run that script to refresh from local LUTs.
LOOK_FIELDS: dict[str, LookField] = {
    "classic": LookField(
        hue_rotation_deg=(-2.12, -3.32, 0.57, 4.12, 3.11, -0.0, -0.89, 0.84, 4.71, 6.06, 3.26, 0.07),
        chroma_ratio=(1.043, 0.928, 0.909, 0.945, 1.002, 1.015, 0.989, 0.949, 0.981, 1.139, 1.165, 1.137),
        mid_chroma_ratio=1.008,
        shadow_chroma_ratio=0.94,
        highlight_chroma_ratio=1.039,
        shadow_cool_a=0.0003,
        shadow_cool_b=-0.0002,
        shadow_l_lo=0.1,
        shadow_l_hi=0.16,
        highlight_l_lo=0.75,
        highlight_l_hi=0.92,
        sat_knee_c=0.2,
        sat_knee_relief=1.085,
        skin_hue_lo=20.0,
        skin_hue_hi=60.0,
        skin_hue_center=40.0,
        skin_hue_pull=0.041,
        skin_chroma_scale=0.961,
    ),
    "reveal": LookField(
        hue_rotation_deg=(-3.48, -3.26, 2.2, 6.49, 5.32, 0.92, 0.05, 1.97, 4.57, 4.88, 2.69, -0.4),
        chroma_ratio=(0.985, 0.897, 0.866, 0.918, 1.011, 0.988, 0.926, 0.801, 0.913, 1.037, 1.066, 1.05),
        mid_chroma_ratio=0.984,
        shadow_chroma_ratio=0.822,
        highlight_chroma_ratio=0.873,
        shadow_cool_a=-0.0004,
        shadow_cool_b=-0.0019,
        shadow_l_lo=0.1,
        shadow_l_hi=0.24,
        highlight_l_lo=0.75,
        highlight_l_hi=0.92,
        sat_knee_c=0.2,
        sat_knee_relief=1.024,
        skin_hue_lo=20.0,
        skin_hue_hi=60.0,
        skin_hue_center=40.0,
        skin_hue_pull=0.001,
        skin_chroma_scale=0.951,
    ),
    "optic_warm_cyan": LookField(
        hue_rotation_deg=(-1.0, -2.5, 1.5, 4.8, 5.2, 2.4, 0.8, -0.6, -1.4, -1.0, 0.4, 0.8),
        chroma_ratio=(1.04, 1.07, 1.00, 0.96, 0.94, 0.98, 1.02, 1.04, 0.98, 0.88, 0.86, 0.94),
        mid_chroma_ratio=1.0,
        shadow_chroma_ratio=0.92,
        highlight_chroma_ratio=1.02,
        shadow_cool_a=-0.0012,
        shadow_cool_b=-0.0020,
        shadow_l_lo=0.10,
        shadow_l_hi=0.22,
        highlight_l_lo=0.74,
        highlight_l_hi=0.92,
        sat_knee_c=0.22,
        sat_knee_relief=1.04,
        skin_hue_lo=20.0,
        skin_hue_hi=64.0,
        skin_hue_center=44.0,
        skin_hue_pull=0.11,
        skin_chroma_scale=1.045,
        skin_warm_a=0.0025,
        skin_warm_b=0.0065,
        neutral_cool_a=-0.0045,
        neutral_cool_b=-0.0060,
        neutral_cool_l_lo=0.16,
        neutral_cool_l_hi=0.66,
        neutral_cool_l_falloff=0.92,
        neutral_cool_chroma_hi=0.078,
        highlight_warm_a=0.0010,
        highlight_warm_b=0.0038,
        highlight_warm_l_lo=0.58,
        highlight_warm_l_hi=0.92,
        highlight_warm_chroma_hi=0.13,
        magenta_hue_lo=292.0,
        magenta_hue_hi=18.0,
        magenta_hue_center=8.0,
        magenta_hue_pull=0.10,
        magenta_chroma_scale=0.78,
    ),
}


def _load_json_fields() -> None:
    """Merge user-measured looks from dngscan_assets/look_fields.json into the registry.

    JSON entries win over same-named built-ins (re-measuring 'classic' overrides it).
    Names reserved for display filters are skipped. Bad entries are skipped, never fatal."""
    try:
        raw = json.loads(LOOK_FIELDS_JSON.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(raw, dict):
        return
    from .display_filter import DISPLAY_FILTERS

    allowed = {f.name for f in dataclass_fields(LookField)}
    for name, params in raw.items():
        if not isinstance(name, str) or not isinstance(params, dict) or name == "none":
            continue
        if name in DISPLAY_FILTERS:
            continue
        try:
            kwargs = {k: (tuple(v) if isinstance(v, list) else v) for k, v in params.items() if k in allowed}
            LOOK_FIELDS[name] = LookField(**kwargs)
        except (TypeError, ValueError):
            continue


_load_json_fields()

LOOK_CHOICES = ("none",) + tuple(LOOK_FIELDS)


def _smoothstep(edge0: float, edge1: float, x: Any) -> Any:
    denom = edge1 - edge0
    if abs(denom) < 1e-9:
        return np.zeros_like(np.asarray(x, dtype=np.float32))
    t = np.clip((x - np.float32(edge0)) / np.float32(denom), 0.0, 1.0)
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
    """Weight 1 in the hue arc interior, soft falloff to 0 within 6° of lo/hi."""
    h = hue_deg % 360.0
    if lo <= hi:
        inside = (h >= lo) & (h <= hi)
        edge = np.minimum(h - lo, hi - h)
    else:
        inside = (h >= lo) | (h <= hi)
        d_lo = np.where(h >= lo, h - lo, 360.0 - lo + h)
        d_hi = np.where(h <= hi, hi - h, 360.0 - h + hi)
        edge = np.minimum(d_lo, d_hi)
    return inside.astype(np.float32) * _smoothstep(0.0, 6.0, edge)


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
        hue = np.degrees(np.arctan2(b2, a2)) % 360.0

    magenta_w = _hue_in_arc(hue, field.magenta_hue_lo, field.magenta_hue_hi) * chroma_w * (1.0 - skin_w)
    if field.magenta_hue_pull > 0.0:
        delta = (field.magenta_hue_center - hue + 180.0) % 360.0 - 180.0
        pull = np.radians(delta) * np.float32(field.magenta_hue_pull) * s * magenta_w
        cos_m = np.cos(pull)
        sin_m = np.sin(pull)
        a3 = a2 * cos_m - b2 * sin_m
        b3 = a2 * sin_m + b2 * cos_m
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
    if field.magenta_chroma_scale != 1.0:
        scale = scale * (1.0 + (np.float32(field.magenta_chroma_scale) - 1.0) * magenta_w)
    scale = 1.0 + (scale - 1.0) * s
    a2 = a2 * scale
    b2 = b2 * scale

    cool_w = s * _smoothstep(field.shadow_l_hi, field.shadow_l_lo, lab_l) * (1.0 - chroma_w)
    if field.shadow_cool_a != 0.0:
        a2 = a2 + np.float32(field.shadow_cool_a) * cool_w
    if field.shadow_cool_b != 0.0:
        b2 = b2 + np.float32(field.shadow_cool_b) * cool_w

    neutral_chroma_w = 1.0 - _smoothstep(
        field.neutral_cool_chroma_hi * 0.45, field.neutral_cool_chroma_hi, chroma
    )
    neutral_l_w = _smoothstep(field.neutral_cool_l_lo, field.neutral_cool_l_hi, lab_l)
    neutral_l_w = neutral_l_w * (1.0 - _smoothstep(field.neutral_cool_l_hi, field.neutral_cool_l_falloff, lab_l))
    neutral_w = s * neutral_chroma_w * neutral_l_w * (1.0 - skin_w)
    if field.neutral_cool_a != 0.0:
        a2 = a2 + np.float32(field.neutral_cool_a) * neutral_w
    if field.neutral_cool_b != 0.0:
        b2 = b2 + np.float32(field.neutral_cool_b) * neutral_w

    skin_l_w = _smoothstep(0.22, 0.58, lab_l) * (1.0 - _smoothstep(0.88, 0.98, lab_l))
    skin_tint_w = s * skin_w * skin_l_w
    if field.skin_warm_a != 0.0:
        a2 = a2 + np.float32(field.skin_warm_a) * skin_tint_w
    if field.skin_warm_b != 0.0:
        b2 = b2 + np.float32(field.skin_warm_b) * skin_tint_w

    highlight_chroma_w = 1.0 - _smoothstep(
        field.highlight_warm_chroma_hi * 0.50, field.highlight_warm_chroma_hi, chroma
    )
    highlight_w = s * highlight_chroma_w * _smoothstep(field.highlight_warm_l_lo, field.highlight_warm_l_hi, lab_l)
    if field.highlight_warm_a != 0.0:
        a2 = a2 + np.float32(field.highlight_warm_a) * highlight_w
    if field.highlight_warm_b != 0.0:
        b2 = b2 + np.float32(field.highlight_warm_b) * highlight_w

    return lab_l, a2, b2
