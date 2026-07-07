# SPDX-License-Identifier: GPL-3.0-or-later
"""Exposure gain and analysis-driven tone compression plans."""
from __future__ import annotations

import math
from typing import Any

from ._deps import np
from . import agx as agx_engine
from . import scene_transform as scene_transform_engine
from .color import (
    apply_rgb_matrix3, clamp_float, luminance_from_rgb_space, output_gamut_space,
    rec2020_to_xyz, smoothstep, XYZ_TO_RGB,
)
from .constants import AGX_INSET, EPS, EV_REPORT_FLOOR, GAMUT_EPS, GRAY_EV, MIDGRAY_HEADROOM_STOPS
from .models import Analysis, RawBundle, ToneCompressionPlan

TONE_CORE_CHOICES = ("agx", "lum")
LUM_NORM_CHOICES = ("y", "power", "max")

def compute_exposure_gain(mode: str, ev: float) -> float:
    """Constant, content-independent exposure anchor plus manual EV compensation.

    neutral stays at the raw-clip=1.0 reference (manual EV only). The tone-mapping
    modes place a nominally-exposed mid gray (~clip / 2**headroom) onto 0.18 so the
    AgX/Tony pivots land on real mid gray. This is a fixed scalar, never derived from
    scene content, so a dark scene stays dark.
    """
    manual = 2.0 ** float(ev)
    if mode == "neutral":
        return manual
    return 0.18 * (2.0 ** MIDGRAY_HEADROOM_STOPS) * manual


def scene_rec2020_to_float(values: Any, scene_scale: float, gain: float = 1.0) -> Any:
    rgb = values.astype(np.float32, copy=False) / np.float32(max(scene_scale, 1.0))
    if gain != 1.0:
        rgb = rgb * np.float32(gain)
    return np.nan_to_num(rgb, nan=0.0, posinf=1e6, neginf=0.0)


def tone_plan_sample_scene_rec2020(
    bundle: RawBundle,
    max_samples: int = 800_000,
    scene_transform: str = "none",
    scene_transform_strength: float = 1.0,
) -> Any:
    flat = bundle.scene_rec2020_render.reshape(-1, bundle.scene_rec2020_render.shape[-1])
    step = max(1, int(math.ceil(flat.shape[0] / max_samples)))
    rec2020 = scene_rec2020_to_float(flat[::step, :3], bundle.scene_scale, bundle.exposure_gain)
    wb_adapt = scene_transform_engine.wb_adaptation_ratios(
        bundle.wb_mode, bundle.camera_wb, bundle.daylight_wb
    )
    return scene_transform_engine.apply_scene_transform_rec2020(
        rec2020, scene_transform, scene_transform_strength, wb_adapt
    )


def _smoothstep_f(edge0: float, edge1: float, x: float) -> float:
    t = clamp_float((x - edge0) / max(edge1 - edge0, 1e-9), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def build_tone_compression_plan(
    bundle: RawBundle,
    analysis: Analysis,
    target_gamut: str,
    ev_from_agx_inset: bool = False,
    scene_transform: str = "none",
    scene_transform_strength: float = 1.0,
    punch_scale: float = 1.0,
    tone_core: str = "agx",
    lum_norm: str = "y",
) -> ToneCompressionPlan:
    rec2020 = tone_plan_sample_scene_rec2020(
        bundle,
        scene_transform=scene_transform,
        scene_transform_strength=scene_transform_strength,
    )
    xyz = rec2020_to_xyz(rec2020)
    y = np.clip(xyz[:, 1], 0.0, None)
    y_for_ev = np.clip(y, 2.0 ** EV_REPORT_FLOOR, None)
    ev_rel = np.log2(y_for_ev) - GRAY_EV
    ev_p1, ev_p50, ev_p99, ev_p999 = [float(v) for v in np.percentile(ev_rel, [1.0, 50.0, 99.0, 99.9])]
    luma_p1, luma_p50, luma_p99, luma_p999 = [float(v) for v in np.percentile(y, [1.0, 50.0, 99.0, 99.9])]

    if ev_from_agx_inset:
        # Derive the AgX log2 window from the exact signal the curve sees: Rec.2020
        # working space, gamut-compressed, run through the inset. Pooling all three inset channels
        # makes the window bracket the brightest channel, so saturated highlights reach the
        # shoulder instead of hard-clipping at the log-encode stage. Luminance percentiles
        # above stay Y-based (they only feed chroma/Tony gain).
        inset = apply_rgb_matrix3(agx_engine.compress_into_gamut(rec2020.astype(np.float32, copy=False)), AGX_INSET)
        inset_v = np.clip(inset.reshape(-1), 2.0 ** EV_REPORT_FLOOR, None)
        ev_ch = np.log2(inset_v) - GRAY_EV
        ev_p1, ev_p99, ev_p999 = [float(v) for v in np.percentile(ev_ch, [1.0, 99.0, 99.9])]

    max_clip = max(analysis.clip_pct.values()) if analysis.clip_pct else 0.0
    clip_term = clamp_float(max_clip / 1.0, 0.0, 1.0)
    gamut_risk = analysis.gamut_out_pct.get(target_gamut, 0.0)
    gamut_term = clamp_float(gamut_risk / 6.0, 0.0, 1.0)

    plan_dr = analysis.usable_dr_eff_ev if math.isfinite(analysis.usable_dr_eff_ev) else analysis.usable_dr_ev
    if math.isfinite(plan_dr):
        noise_limited_black = -plan_dr - 1.5
    else:
        noise_limited_black = -12.0
    black_ev = max(ev_p1 - 0.25, noise_limited_black)
    black_ev = clamp_float(black_ev, -14.0, -2.0)

    white_margin = 0.25 + 0.35 * clip_term + 0.20 * gamut_term
    white_ev = max(ev_p999 + white_margin, ev_p99 + 0.10, 1.5)
    white_ev = clamp_float(white_ev, 1.2, 8.5)
    if white_ev - black_ev < 5.5:
        black_ev = white_ev - 5.5

    # Bright-scene gate (median luminance near mid gray; exposure- and transform-aware).
    # Drives the shadow relief and the punch strength: night scenes gate to zero.
    w_bright = _smoothstep_f(-3.0, -1.2, ev_p50)

    dynamic_range_ev = white_ev - black_ev
    shadow_term = clamp_float((10.0 - plan_dr) / 3.0, 0.0, 1.0) if math.isfinite(plan_dr) else 0.5
    shoulder_strength = max(clip_term, gamut_term)
    contrast = clamp_float(3.0 - 0.25 * shoulder_strength + 0.10 * clamp_float((9.0 - dynamic_range_ev) / 4.0, 0.0, 1.0), 2.45, 3.15)
    toe_power = clamp_float(1.5 - 0.25 * shadow_term, 1.15, 1.75)
    # Shadow relief for bright scenes: a gentler toe lifts crushed shadows. Measured to be
    # nearly colour-neutral, unlike widening black_ev (which flattens the window and washes
    # subject colour ~20% — the opposite of the punch below, so it is deliberately not used).
    toe_power = clamp_float(toe_power - 0.20 * w_bright, 1.15, 1.75)
    shoulder_power = clamp_float(3.3 - 0.85 * shoulder_strength, 2.10, 3.60)
    # Scene-driven latitude, shoulder side only: wider tonal windows earn a longer
    # linear run above the pivot so daylight subject colors are not washed from mid
    # gray up. The toe side stays at zero — a lower run makes the recomputed toe
    # steeper and darkens deep shadows (measured), the opposite of what we want.
    latitude_hi_ev = clamp_float(0.25 * dynamic_range_ev, 1.0, 2.0)
    latitude_lo_ev = 0.0

    # Punch (post-AgX purity compensation, dngscan/punch.py): bright scenes with a
    # quality sensor window (low ISO per priors) and a wide tonal window are the washed
    # case; night/high-ISO gates to exactly zero, which short-circuits the operator so
    # those renders stay byte-identical.
    w_quality = _smoothstep_f(7.5, 9.5, plan_dr) if math.isfinite(plan_dr) else 0.5
    w_dr = _smoothstep_f(6.5, 8.0, dynamic_range_ev)
    punch_strength = clamp_float(
        w_bright * w_quality * (0.55 + 0.45 * w_dr) * clamp_float(punch_scale, 0.0, 1.5), 0.0, 1.0
    )
    if tone_core == "lum":
        punch_strength = 0.0

    if target_gamut == "Rec2020":
        rgb = rec2020
    else:
        rgb = apply_rgb_matrix3(xyz, XYZ_TO_RGB[target_gamut])
    rgb = np.nan_to_num(rgb, nan=0.0, posinf=1e6, neginf=-1e6)
    anchor = np.maximum(y, 0.0)
    chroma_ratio = np.max(np.abs(rgb - anchor[:, None]), axis=1) / np.maximum(anchor, EPS)
    finite_chroma = chroma_ratio[np.isfinite(chroma_ratio) & (anchor > 2.0 ** EV_REPORT_FLOOR)]
    chroma_p95 = float(np.percentile(finite_chroma, 95.0)) if finite_chroma.size else 0.0
    chroma_term = clamp_float((chroma_p95 - 3.0) / 4.0, 0.0, 1.0)
    chroma_strength = clamp_float(max(gamut_term, 0.85 * clip_term, chroma_term), 0.0, 1.0)

    negative_rgb_pct = float(np.mean(np.min(rgb, axis=1) < -GAMUT_EPS) * 100.0)
    over_rgb_pct = float(np.mean(np.max(rgb, axis=1) > 1.0 + GAMUT_EPS) * 100.0)
    target_white_y = 0.18 * (2.0 ** white_ev)
    observed_white_y = max(luma_p999, 0.18)
    tony_hdr_gain = clamp_float(target_white_y / observed_white_y, 1.0, 2.2)

    return ToneCompressionPlan(
        target_gamut=target_gamut,
        luma_p1=luma_p1,
        luma_p50=luma_p50,
        luma_p99=luma_p99,
        luma_p999=luma_p999,
        black_ev=black_ev,
        white_ev=white_ev,
        dynamic_range_ev=dynamic_range_ev,
        contrast=contrast,
        toe_power=toe_power,
        shoulder_power=shoulder_power,
        latitude_lo_ev=latitude_lo_ev,
        latitude_hi_ev=latitude_hi_ev,
        punch_strength=punch_strength,
        chroma_strength=chroma_strength,
        chroma_p95=chroma_p95,
        negative_rgb_pct=negative_rgb_pct,
        over_rgb_pct=over_rgb_pct,
        tony_hdr_gain=tony_hdr_gain,
        tone_core=tone_core,
        lum_norm=lum_norm,
    )


def plan_for_mode(
    bundle: RawBundle,
    analysis: Analysis,
    mode: str,
    output_gamut: str = "srgb",
    scene_transform: str = "none",
    scene_transform_strength: float = 1.0,
    punch_scale: float = 1.0,
    tone_core: str = "agx",
    lum_norm: str = "y",
) -> ToneCompressionPlan:
    """Build the tone plan in the space each mode actually works in.

    smart operates in the selected output space, Tony uses its authored linear-sRGB
    LUT stimulus, and AgX stays in Rec.2020 and derives its log2 window from the
    Rec.2020 inset signal it curves.
    """
    tone_core = tone_core if tone_core in TONE_CORE_CHOICES else "agx"
    lum_norm = lum_norm if lum_norm in LUM_NORM_CHOICES else "y"
    if mode == "agx" or tone_core == "lum":
        target_gamut = "Rec2020"
    elif mode == "tony":
        target_gamut = "sRGB"
    else:
        target_gamut = output_gamut_space(output_gamut)
    return build_tone_compression_plan(
        bundle,
        analysis,
        target_gamut,
        ev_from_agx_inset=(mode == "agx" and tone_core == "agx"),
        scene_transform=scene_transform if mode == "agx" else "none",
        scene_transform_strength=scene_transform_strength,
        punch_scale=punch_scale if mode == "agx" and tone_core == "agx" else 0.0,
        tone_core=tone_core,
        lum_norm=lum_norm,
    )
