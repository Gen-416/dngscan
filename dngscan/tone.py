# SPDX-License-Identifier: GPL-3.0-or-later
"""Exposure gain and analysis-driven tone compression plans."""
from __future__ import annotations

import math
from typing import Any

from ._deps import np
from . import agx as agx_engine
from .color import (
    apply_rgb_matrix3, clamp_float, luminance_from_rgb_space, output_gamut_space,
    rec2020_to_xyz, smoothstep, XYZ_TO_RGB,
)
from .constants import AGX_INSET, EPS, EV_REPORT_FLOOR, GAMUT_EPS, GRAY_EV, MIDGRAY_HEADROOM_STOPS
from .models import Analysis, RawBundle, ToneCompressionPlan

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


def smooth_highlight_shoulder(y: Any, knee: float) -> Any:
    """Identity below the knee (midtones untouched); a globally smooth exponential
    roll-off that asymptotes to display white above it. Value and unit slope match at the
    knee, so there is no contour-inducing kink -- the branch below only avoids a needless
    exp() on the untouched midtones."""
    knee = clamp_float(knee, 0.05, 0.98)
    span = 1.0 - knee
    over = np.maximum(y - np.float32(knee), 0.0)
    rolled = np.float32(knee) + np.float32(span) * (1.0 - np.exp(-over / np.float32(max(span, EPS))))
    return np.where(y > np.float32(knee), rolled, y)


def smart_mapping_strength(analysis: Analysis, plan: ToneCompressionPlan | None = None) -> float:
    target_gamut = plan.target_gamut if plan is not None else "sRGB"
    srgb_risk = analysis.gamut_out_pct.get(target_gamut, analysis.gamut_out_pct.get("sRGB", 0.0))
    if plan is not None:
        srgb_risk = max(srgb_risk, plan.over_rgb_pct)
    clip_pressure = max(analysis.clip_pct.values()) if analysis.clip_pct else 0.0
    if plan is None:
        highlight_pressure = max(0.0, 1.0 + analysis.ev_p999)
    else:
        highlight_pressure = clamp_float((plan.luma_p999 - 0.65) / 0.35, 0.0, 1.0)
    gamut_term = min(1.0, srgb_risk / 6.0)
    clip_term = min(1.0, clip_pressure / 1.0)
    chroma_term = clamp_float((plan.chroma_p95 - 3.0) / 4.0, 0.0, 1.0) if plan is not None else 0.0
    return float(max(gamut_term, clip_term, highlight_pressure * 0.7, 0.8 * chroma_term))


def tone_plan_sample_scene_rec2020(bundle: RawBundle, max_samples: int = 800_000) -> Any:
    flat = bundle.scene_rec2020_render.reshape(-1, bundle.scene_rec2020_render.shape[-1])
    step = max(1, int(math.ceil(flat.shape[0] / max_samples)))
    return scene_rec2020_to_float(flat[::step, :3], bundle.scene_scale, bundle.exposure_gain)


def build_tone_compression_plan(
    bundle: RawBundle, analysis: Analysis, target_gamut: str, ev_from_agx_inset: bool = False
) -> ToneCompressionPlan:
    rec2020 = tone_plan_sample_scene_rec2020(bundle)
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

    dynamic_range_ev = white_ev - black_ev
    shadow_term = clamp_float((10.0 - plan_dr) / 3.0, 0.0, 1.0) if math.isfinite(plan_dr) else 0.5
    shoulder_strength = max(clip_term, gamut_term)
    contrast = clamp_float(3.0 - 0.25 * shoulder_strength + 0.10 * clamp_float((9.0 - dynamic_range_ev) / 4.0, 0.0, 1.0), 2.45, 3.15)
    toe_power = clamp_float(1.5 - 0.25 * shadow_term, 1.15, 1.75)
    shoulder_power = clamp_float(3.3 - 0.85 * shoulder_strength, 2.10, 3.60)

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
        chroma_strength=chroma_strength,
        chroma_p95=chroma_p95,
        negative_rgb_pct=negative_rgb_pct,
        over_rgb_pct=over_rgb_pct,
        tony_hdr_gain=tony_hdr_gain,
    )


def precondition_tonemapper_rgb(rgb: Any, luma: Any, plan: ToneCompressionPlan, for_tony: bool = False) -> Any:
    """Split Y/chroma, then condition chroma and highlights from whole-frame stats."""
    anchor = np.clip(luma.astype(np.float32, copy=False), 0.0, None)
    out = rgb.astype(np.float32, copy=True)
    out = np.nan_to_num(out, nan=0.0, posinf=1.0, neginf=0.0)

    if for_tony and plan.tony_hdr_gain > 1.0:
        edge0 = max(0.18, plan.luma_p99 * 0.55)
        edge1 = max(edge0 + 0.02, plan.luma_p999)
        weight = smoothstep(edge0, edge1, anchor)
        gain = 1.0 + (plan.tony_hdr_gain - 1.0) * weight
        out *= gain[:, None]
        anchor = anchor * gain

    rgb_min = np.min(out, axis=1)
    low = (rgb_min < 0.0) & (rgb_min < anchor - EPS)
    if np.any(low):
        scale = (0.0 - anchor[low]) / (rgb_min[low] - anchor[low])
        scale = np.clip(scale, 0.0, 1.0)
        out[low] = anchor[low, None] + scale[:, None] * (out[low] - anchor[low, None])

    strength = plan.chroma_strength
    if strength > 0.0:
        chroma = out - anchor[:, None]
        chroma_mag = np.max(np.abs(chroma), axis=1)
        chroma_ratio = chroma_mag / np.maximum(anchor, EPS)
        high_luma = smoothstep(max(0.18, plan.luma_p99 * 0.50), max(0.22, plan.luma_p999), anchor)
        high_chroma = smoothstep(0.50, max(0.80, plan.chroma_p95), chroma_ratio)
        weight = np.maximum(high_luma, high_chroma)
        max_reduction = 0.38 if for_tony else 0.30
        chroma_scale = 1.0 - max_reduction * strength * weight
        out = anchor[:, None] + chroma_scale[:, None] * chroma

    return out


def compress_linear_output_rgb_for_jpeg(
    rgb: Any, analysis: Analysis, plan: ToneCompressionPlan | None = None, output_gamut: str = "srgb"
) -> Any:
    strength = smart_mapping_strength(analysis, plan)
    if strength <= 0.0:
        return np.nan_to_num(rgb.astype(np.float32, copy=False), nan=0.0, posinf=1e6, neginf=-1e6)

    rgb = np.nan_to_num(rgb.astype(np.float32, copy=False), nan=0.0, posinf=1e6, neginf=-1e6)
    # Anchor on this pixel's own output-space luminance, so the luminance-preserving math
    # below stays exact instead of mixing Rec.2020 Y with the encoded output RGB space.
    y = luminance_from_rgb_space(rgb, output_gamut)
    # Analysis drives where the highlight roll-off begins: more clip/gamut/highlight/chroma
    # pressure pulls the knee down so bright detail is compressed sooner.
    knee = clamp_float(0.88 - 0.38 * strength, 0.50, 0.90)
    y_mapped = smooth_highlight_shoulder(y, knee)
    scale_y = np.divide(y_mapped, np.maximum(y, EPS), out=np.ones_like(y_mapped), where=y > EPS)
    rgb = rgb * scale_y[:, None]
    anchor = np.clip(y_mapped, 0.0, 1.0)

    # Analysis-driven chroma easing: ease saturation only where the frame is bright or where
    # chroma exceeds the scene's own 95th-percentile chroma (from the plan), not everywhere.
    if plan is not None:
        chroma = rgb - anchor[:, None]
        chroma_ratio = np.max(np.abs(chroma), axis=1) / np.maximum(anchor, EPS)
        high_luma = smoothstep(max(0.30, knee - 0.10), 0.999, anchor)
        high_chroma = smoothstep(0.50, max(0.80, plan.chroma_p95), chroma_ratio)
        weight = np.maximum(high_luma, high_chroma)
        rgb = anchor[:, None] + (1.0 - 0.30 * strength * weight)[:, None] * chroma

    # Out-of-gamut is handled downstream by the shared Oklab gamut fit, so return the
    # tone-shaped linear RGB unclipped (hue preservation happens in Oklab, not per-channel).
    return np.nan_to_num(rgb.astype(np.float32, copy=False), nan=0.0, posinf=1e6, neginf=-1e6)


def plan_for_mode(
    bundle: RawBundle, analysis: Analysis, mode: str, output_gamut: str = "srgb"
) -> ToneCompressionPlan:
    """Build the tone plan in the space each mode actually works in.

    smart operates in the selected output space, Tony uses its authored linear-sRGB
    LUT stimulus, and AgX stays in Rec.2020 and derives its log2 window from the
    Rec.2020 inset signal it curves.
    """
    if mode == "agx":
        target_gamut = "Rec2020"
    elif mode == "tony":
        target_gamut = "sRGB"
    else:
        target_gamut = output_gamut_space(output_gamut)
    return build_tone_compression_plan(bundle, analysis, target_gamut, ev_from_agx_inset=(mode == "agx"))

