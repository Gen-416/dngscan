# SPDX-License-Identifier: GPL-3.0-or-later
"""RAW-derived permission maps for gated display rendering.

RAW evidence controls how much the DRT may alter hue/chroma; scene RGB controls
appearance; output gamut controls final constraint. These weights are not style masks.
"""
from __future__ import annotations

import math
from typing import Any

from ._deps import np
from .color import OKLAB_M1, OKLAB_M2, apply_rgb_matrix3, rec2020_to_xyz, smoothstep
from .constants import EPS
from .models import Analysis, RawBundle, RawGuidanceMaps

# Discrete CFA clip classes (bit flags): R=1, G=2, B=4.
CLIP_CLASS_NONE = 0
CLIP_CLASS_R = 1
CLIP_CLASS_G = 2
CLIP_CLASS_B = 4
CLIP_CLASS_RG = 3
CLIP_CLASS_RB = 5
CLIP_CLASS_GB = 6
CLIP_CLASS_RGB = 7


def clip_class_from_masks(masks_rgb: Any, threshold: float = 0.35) -> Any:
    """Per-pixel discrete clip class from soft R/G/B CFA masks."""
    m = np.clip(np.asarray(masks_rgb, dtype=np.float32), 0.0, 1.0)
    flags = (
        (m[:, 0] > np.float32(threshold)).astype(np.int32)
        | ((m[:, 1] > np.float32(threshold)).astype(np.int32) << 1)
        | ((m[:, 2] > np.float32(threshold)).astype(np.int32) << 2)
    )
    return flags


def headroom_from_masks(masks_rgb: Any) -> Any:
    """Continuous per-channel headroom remainder (1 = full, 0 = saturated)."""
    m = np.clip(np.asarray(masks_rgb, dtype=np.float32), 0.0, 1.0)
    return np.clip(np.float32(1.0) - m, 0.0, 1.0)


def raw_color_permission(masks_rgb: Any) -> Any:
    """How much RAW evidence permits chroma/path-to-white work (0 = trust scene color)."""
    m = np.clip(np.asarray(masks_rgb, dtype=np.float32), 0.0, 1.0)
    mr, mg, mb = m[:, 0], m[:, 1], m[:, 2]
    # Continuous combination (G-only weakest, multi-channel strongest).
    strength = np.float32(1.0) - (
        (np.float32(1.0) - np.float32(0.40) * mg)
        * (np.float32(1.0) - np.float32(0.55) * mr)
        * (np.float32(1.0) - np.float32(0.55) * mb)
    )
    classes = clip_class_from_masks(m)
    multi = (classes >= CLIP_CLASS_RG).astype(np.float32)
    return np.clip(strength + np.float32(0.12) * multi, 0.0, 1.0)


def scene_highlight_permission(
    scene_ev: Any,
    ev_lo: float = 0.25,
    ev_hi: float = 2.75,
) -> Any:
    """Open color-path only in scene-luminance shoulder (independent of RAW clip)."""
    return smoothstep(np.float32(ev_lo), np.float32(ev_hi), np.asarray(scene_ev, dtype=np.float32))


def midtone_protection(
    scene_ev: Any,
    raw_permission: Any,
    strength: float = 0.92,
) -> Any:
    """Suppress color-path in trustworthy midtones (portraits, costumes, props)."""
    ev = np.asarray(scene_ev, dtype=np.float32)
    raw = np.clip(np.asarray(raw_permission, dtype=np.float32), 0.0, 1.0)
    body = np.float32(1.0) - smoothstep(np.float32(-2.5), np.float32(0.35), ev)
    return np.clip(np.float32(strength) * body * (np.float32(1.0) - raw), 0.0, 1.0)


def color_path_weight(
    masks_rgb: Any | None,
    scene_ev: Any,
    gamut_pressure_pct: float = 0.0,
    *,
    scene_rgb_rec2020: Any | None = None,
    noise_ev_floor: float | None = None,
    midtone_protect: float = 0.92,
    highlight_ev_lo: float = 0.25,
    highlight_ev_hi: float = 2.75,
    gamut_pressure_scale: float = 0.30,
) -> Any:
    """Blend weight for AgX color geometry over luma-first DRT (per pixel, 0–1)."""
    ev = np.asarray(scene_ev, dtype=np.float32)
    if masks_rgb is not None and masks_rgb.shape[0] == ev.shape[0]:
        raw_perm = raw_color_permission(masks_rgb)
    else:
        raw_perm = np.zeros_like(ev, dtype=np.float32)
    scene_perm = scene_highlight_permission(ev, highlight_ev_lo, highlight_ev_hi)
    gamut_perm = np.float32(gamut_pressure_scale) * np.float32(
        min(1.0, max(0.0, float(gamut_pressure_pct) / 8.0))
    )
    w = np.maximum(raw_perm, scene_perm * np.float32(0.45)) + gamut_perm
    if noise_ev_floor is not None:
        w = w * snr_confidence_from_ev(ev, float(noise_ev_floor))
    protect = midtone_protection(ev, raw_perm, midtone_protect)
    w = np.clip(w * (np.float32(1.0) - protect), 0.0, 1.0)
    if scene_rgb_rec2020 is not None and scene_rgb_rec2020.shape[0] == ev.shape[0]:
        w = w * sector_hue_multiplier(scene_rgb_rec2020, ev)
    return w.astype(np.float32, copy=False)


def snr_confidence_from_ev(scene_ev: Any, noise_ev_floor: float) -> Any:
    """Trust scene color more as luminance rises above the noise floor."""
    ev = np.asarray(scene_ev, dtype=np.float32)
    lo = np.float32(noise_ev_floor + 1.5)
    hi = np.float32(noise_ev_floor + 5.5)
    return smoothstep(lo, hi, ev).astype(np.float32, copy=False)


def _rec2020_oklab_hue_deg(rgb: Any) -> Any:
    xyz = rec2020_to_xyz(rgb)
    lms = apply_rgb_matrix3(xyz, OKLAB_M1)
    lab = apply_rgb_matrix3(np.cbrt(np.maximum(lms, np.float32(EPS))), OKLAB_M2)
    return (np.degrees(np.arctan2(lab[:, 2], lab[:, 1])) % np.float32(360.0)).astype(
        np.float32, copy=False
    )


def sector_hue_multiplier(scene_rgb_rec2020: Any, scene_ev: Any) -> Any:
    """Skin midtone protect + green/cyan highlight openness (hue-path policy)."""
    rgb = np.asarray(scene_rgb_rec2020, dtype=np.float32).reshape(-1, 3)
    ev = np.asarray(scene_ev, dtype=np.float32).reshape(-1)
    hue = _rec2020_oklab_hue_deg(rgb)
    skin = smoothstep(np.float32(22.0), np.float32(38.0), hue) * (
        np.float32(1.0) - smoothstep(np.float32(68.0), np.float32(82.0), hue)
    )
    skin *= smoothstep(np.float32(-1.25), np.float32(0.35), ev) * (
        np.float32(1.0) - smoothstep(np.float32(1.35), np.float32(2.35), ev)
    )
    green = smoothstep(np.float32(128.0), np.float32(148.0), hue) * (
        np.float32(1.0) - smoothstep(np.float32(188.0), np.float32(208.0), hue)
    )
    green *= smoothstep(np.float32(0.35), np.float32(1.85), ev)
    return np.clip(
        (np.float32(1.0) - np.float32(0.32) * skin) * (np.float32(1.0) + np.float32(0.14) * green),
        np.float32(0.55),
        np.float32(1.18),
    ).astype(np.float32, copy=False)


def build_raw_guidance_maps(
    bundle: RawBundle,
    analysis: Analysis | None = None,
) -> RawGuidanceMaps | None:
    """Build half-resolution RAW permission rasters from CFA clip masks."""
    masks = getattr(bundle, "clip_masks", None)
    if masks is None:
        return None
    m = np.asarray(masks, dtype=np.float32)
    h, w = m.shape[:2]
    flat = m.reshape(-1, 3)
    headroom = headroom_from_masks(flat).reshape(h, w, 3).astype(np.float16, copy=False)
    clip_class = clip_class_from_masks(flat).reshape(h, w).astype(np.uint8, copy=False)
    from .tone import scene_rec2020_to_float

    scene_f = scene_rec2020_to_float(
        bundle.scene_rec2020_render.reshape(-1, 3)[: h * w, :3],
        bundle.scene_scale,
        bundle.exposure_gain,
    )
    ev = scene_ev_from_rec2020(scene_f).reshape(h, w)
    noise_floor = -12.0
    if analysis is not None and math.isfinite(analysis.usable_dr_eff_ev):
        noise_floor = -float(analysis.usable_dr_eff_ev) - 1.0
    snr = snr_confidence_from_ev(ev.reshape(-1), noise_floor).reshape(h, w).astype(
        np.float16, copy=False
    )
    return RawGuidanceMaps(headroom=headroom, clip_class=clip_class, snr_confidence=snr)


def ensure_raw_guidance(bundle: RawBundle, analysis: Analysis | None = None) -> RawGuidanceMaps | None:
    if getattr(bundle, "raw_guidance", None) is not None:
        return bundle.raw_guidance
    maps = build_raw_guidance_maps(bundle, analysis)
    bundle.raw_guidance = maps
    return maps


def scene_ev_from_rec2020(rgb_rec2020: Any) -> Any:
    """Scene EV relative to 18% gray from Rec.2020 linear RGB."""
    from .color import luminance_from_rec2020

    y = np.maximum(luminance_from_rec2020(rgb_rec2020), np.float32(EPS))
    return np.log2(y / np.float32(0.18)).astype(np.float32, copy=False)
