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
    rec2020_to_xyz, XYZ_TO_RGB,
)
from .constants import EPS, EV_REPORT_FLOOR, GAMUT_EPS, GRAY_EV, MIDGRAY_HEADROOM_STOPS
from . import retreat as retreat_engine
from .models import (
    Analysis, ColorGeometryPlan, RawBundle, RenderPlan, SceneToneMetrics,
    ToneCompressionPlan,
)

TONE_CORE_CHOICES = ("gated", "agx", "lum", "neutral")
LUM_NORM_CHOICES = ("y", "power", "max")


def exposure_mode_for_tone_core(tone_core: str) -> str:
    """Map tone-core selection to the exposure anchor used by compute_exposure_gain."""
    if tone_core == "neutral":
        return "neutral"
    return "agx"


def neutral_tone_plan(target_gamut: str) -> ToneCompressionPlan:
    """Placeholder plan for the direct (no tone-map) path; curve fields are unused."""
    return ToneCompressionPlan(
        target_gamut=target_gamut,
        luma_p1=0.0,
        luma_p50=0.0,
        luma_p99=0.0,
        luma_p999=0.0,
        black_ev=-10.0,
        white_ev=6.5,
        dynamic_range_ev=16.5,
        contrast=3.0,
        toe_power=1.5,
        shoulder_power=3.3,
        chroma_p95=0.0,
        negative_rgb_pct=0.0,
        over_rgb_pct=0.0,
        tone_core="neutral",
    )

def compute_exposure_gain(mode: str, ev: float) -> float:
    """Constant, content-independent exposure anchor plus manual EV compensation.

    neutral stays at the raw-clip=1.0 reference (manual EV only). The tone-mapping
    cores place a nominally-exposed mid gray (~clip / 2**headroom) onto 0.18 so the
    curve pivot lands on real mid gray. This is a fixed scalar, never derived from
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


def subsample_step(pixel_count: int, max_samples: int = 800_000) -> int:
    return max(1, int(math.ceil(pixel_count / max_samples)))


def tone_plan_sample_scene_rec2020(
    bundle: RawBundle,
    max_samples: int = 800_000,
    scene_transform: str = "none",
    scene_transform_strength: float = 1.0,
    exposure_gain: float | None = None,
) -> Any:
    flat = bundle.scene_rec2020_render.reshape(-1, bundle.scene_rec2020_render.shape[-1])
    step = subsample_step(flat.shape[0], max_samples)
    gain = bundle.exposure_gain if exposure_gain is None else exposure_gain
    rec2020 = scene_rec2020_to_float(flat[::step, :3], bundle.scene_scale, gain)
    wb_adapt = scene_transform_engine.wb_adaptation_ratios(
        bundle.wb_mode, bundle.camera_wb, bundle.daylight_wb
    )
    return scene_transform_engine.apply_scene_transform_rec2020(
        rec2020, scene_transform, scene_transform_strength, wb_adapt
    )


def scene_tone_metrics(
    bundle: RawBundle,
    analysis: Analysis,
    scene_transform: str = "none",
    scene_transform_strength: float = 1.0,
    plan_exposure_gain: float | None = None,
    max_samples: int = 800_000,
) -> SceneToneMetrics:
    """Measure the reliable scene body separately from its highlight tail.

    Reconstruction may make a clipped lamp visually plausible, but it cannot restore its
    sensor headroom. We therefore exclude soft CFA-clipped sites from body percentiles
    while retaining the complete rendered tail for topology classification.
    """
    flat = bundle.scene_rec2020_render.reshape(-1, bundle.scene_rec2020_render.shape[-1])
    step = subsample_step(flat.shape[0], max_samples)
    gain = bundle.exposure_gain if plan_exposure_gain is None else plan_exposure_gain
    rec = scene_rec2020_to_float(flat[::step, :3], bundle.scene_scale, gain)
    wb_adapt = scene_transform_engine.wb_adaptation_ratios(
        bundle.wb_mode, bundle.camera_wb, bundle.daylight_wb
    )
    rec = scene_transform_engine.apply_scene_transform_rec2020(
        rec, scene_transform, scene_transform_strength, wb_adapt
    )
    y = np.clip(rec2020_to_xyz(rec)[:, 1], 2.0 ** EV_REPORT_FLOOR, None)
    ev = np.log2(y) - GRAY_EV

    reliable = np.ones((ev.shape[0],), dtype=bool)
    if getattr(bundle, "clip_masks", None) is not None:
        masks = retreat_engine.clip_masks_for_shape(bundle, bundle.scene_rec2020_render.shape[:2])
        reliable = np.max(masks.reshape(-1, 3)[::step], axis=1) < np.float32(0.10)
    reliable_ev = ev[reliable]
    if reliable_ev.size < max(256, ev.size // 20):
        reliable_ev = ev
        reliable = np.ones((ev.shape[0],), dtype=bool)

    p1, p5, p50, p95, p99, p999 = [
        float(v) for v in np.percentile(reliable_ev, [1.0, 5.0, 50.0, 95.0, 99.0, 99.9])
    ]
    tail_p9999 = float(np.percentile(ev, 99.99))
    reliable_tail_p9999 = float(np.percentile(reliable_ev, 99.99))
    tail0 = float(np.mean(ev > 0.0) * 100.0)
    tail2 = float(np.mean(ev > 2.0) * 100.0)
    extremity = tail2 / max(tail0, 1e-4)
    sparse_emitter = bool(tail0 < 3.0 and extremity > 0.12)
    return SceneToneMetrics(
        reliable_sample_pct=float(np.mean(reliable) * 100.0),
        body_ev_p1=p1,
        body_ev_p5=p5,
        body_ev_p50=p50,
        body_ev_p95=p95,
        body_ev_p99=p99,
        body_ev_p999=p999,
        tail_ev_p9999=tail_p9999,
        tail_area_ev0_pct=tail0,
        tail_area_ev2_pct=tail2,
        tail_extremity=extremity,
        sparse_emitter_tail=sparse_emitter,
        raw_clip_union_pct=float(analysis.cell_union_pct),
        reliable_tail_ev_p9999=reliable_tail_p9999,
    )


def build_color_geometry_plan(
    analysis: Analysis, output_gamut: str, tone_core: str = "agx"
) -> ColorGeometryPlan:
    space = output_gamut_space(output_gamut)
    pressure = float(analysis.gamut_out_pct.get(space, 0.0))
    # The output fit reacts slightly sooner in the smaller sRGB container and grows its
    # adaptive-L0 safety margin as measured output-gamut pressure rises. It remains a
    # colour-only decision: no tone endpoint or contrast parameter reads this value.
    base_alpha = 0.045 if output_gamut == "p3" else 0.060
    alpha = base_alpha + 0.015 * clamp_float(pressure / 5.0, 0.0, 1.0)
    if tone_core == "gated":
        noise_floor = -12.0
        if math.isfinite(analysis.usable_dr_eff_ev):
            noise_floor = -float(analysis.usable_dr_eff_ev) - 1.0
        return ColorGeometryPlan(
            target_gamut=output_gamut,
            raw_clip_retreat_strength=0.0,
            output_gamut_pressure_pct=pressure,
            gamut_fit_alpha=alpha,
            display_highlight_chroma_retreat=0.28,
            color_path_master=1.0,
            gated_midtone_protect=0.92,
            color_path_highlight_ev_lo=0.25,
            color_path_highlight_ev_hi=2.75,
            gated_noise_ev_floor=noise_floor,
        )
    return ColorGeometryPlan(
        target_gamut=output_gamut,
        # Neutral is a diagnostic scene-linear reference, so it must not hide clipped
        # colour by applying the delivery transform's retreat operator.
        raw_clip_retreat_strength=0.0 if tone_core == "neutral" else 1.0,
        output_gamut_pressure_pct=pressure,
        gamut_fit_alpha=alpha,
        display_highlight_chroma_retreat=0.35 if tone_core == "lum" else 0.0,
    )


def _smoothstep_f(edge0: float, edge1: float, x: float) -> float:
    """Scalar smoothstep retained for the separate AgX colour-punch gate."""
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
    agx_primaries: str = "smooth",
    plan_exposure_gain: float | None = None,
    scene_metrics: SceneToneMetrics | None = None,
) -> ToneCompressionPlan:
    agx_primaries = agx_engine.resolve_agx_primaries(agx_primaries)
    if tone_core == "neutral":
        return neutral_tone_plan(target_gamut)

    plan_gain = plan_exposure_gain if plan_exposure_gain is not None else bundle.exposure_gain
    metrics = scene_metrics if scene_metrics is not None else scene_tone_metrics(
        bundle,
        analysis,
        scene_transform,
        scene_transform_strength,
        plan_gain,
    )
    rec2020 = tone_plan_sample_scene_rec2020(
        bundle, scene_transform=scene_transform, scene_transform_strength=scene_transform_strength,
        exposure_gain=plan_gain,
    )
    xyz = rec2020_to_xyz(rec2020)
    y = np.clip(xyz[:, 1], 0.0, None)
    ev_p1 = metrics.body_ev_p1
    ev_p50 = metrics.body_ev_p50
    ev_p99 = metrics.body_ev_p99
    ev_p999 = metrics.body_ev_p999
    luma_p1, luma_p50, luma_p99, luma_p999 = [float(v) for v in np.percentile(y, [1.0, 50.0, 99.0, 99.9])]

    plan_dr = analysis.usable_dr_eff_ev if math.isfinite(analysis.usable_dr_eff_ev) else analysis.usable_dr_ev
    if math.isfinite(plan_dr):
        noise_limited_black = -plan_dr - 1.5
    else:
        noise_limited_black = -12.0
    black_ev = max(ev_p1 - 0.25, noise_limited_black)
    black_ev = clamp_float(black_ev, -14.0, -1.5)
    # darktable's C1 curve starts toe/shoulder at the pivot by default. Do not map a
    # dark scene's p95 directly to the shoulder: when p95 < 0 EV, that segment crosses
    # the calibrated pivot and creates exactly the dark-frame / glaring-lamp failure.
    latitude_lo_ev = 0.10
    latitude_hi_ev = 0.20 if not metrics.sparse_emitter_tail else 0.0
    toe_start_ev = -latitude_lo_ev
    shoulder_start_ev = latitude_hi_ev

    # The complete tail describes topology (for example, sparse emitters), but has no
    # authority over the global white endpoint: reconstructed/RAW-clipped values are not
    # measured scene radiometry. Only the reliable tail may set the shoulder endpoint.
    white_margin = 0.50 if metrics.sparse_emitter_tail else 0.30
    min_white_ev = 3.50 if metrics.sparse_emitter_tail else 3.00
    reliable_white_tail = metrics.reliable_tail_ev_p9999
    if not math.isfinite(reliable_white_tail):
        reliable_white_tail = metrics.tail_ev_p9999
    white_ev = max(reliable_white_tail + white_margin, min_white_ev)
    white_ev = clamp_float(white_ev, min_white_ev, 8.5)

    # These are strictly tone decisions. Colour clipping and output gamut live in
    # ColorGeometryPlan and must not change either curve endpoint or pivot contrast.
    dynamic_range_ev = white_ev - black_ev
    contrast = 3.0
    dark_body = clamp_float((-metrics.body_ev_p50 - 1.5) / 3.0, 0.0, 1.0)
    toe_power = 1.50 - 0.35 * dark_body
    shoulder_power = 2.55 if metrics.sparse_emitter_tail else 2.90
    # darktable exposes pivot position and pivot target output separately. Our automatic
    # path has no independent pivot target, so moving its pivot would silently move the
    # calibrated EV=0 -> 18% anchor. Keep the anchor fixed until a constrained solver
    # can satisfy both conditions.
    pivot_ev_offset = 0.0
    target_black_linear = 0.0
    shadow_quality = _smoothstep_f(5.5, 8.5, plan_dr) if math.isfinite(plan_dr) else 0.5
    view_brightness = 1.0 + 0.30 * dark_body * shadow_quality
    # Punch is a post-core chroma operator, not a tone decision: it is calculated after
    # endpoint selection and cannot feed back into pivot, toe, shoulder or exposure.
    # The luminance core deliberately stays at zero because it already retains the
    # original RGB ratio through the body; neutral is a diagnostic reference.
    if tone_core in ("agx", "gated"):
        w_bright = _smoothstep_f(-3.0, -1.2, metrics.body_ev_p50)
        w_quality = _smoothstep_f(7.5, 9.5, plan_dr) if math.isfinite(plan_dr) else 0.5
        w_dr = _smoothstep_f(6.5, 8.0, dynamic_range_ev)
        punch_strength = clamp_float(
            w_bright * w_quality * (0.55 + 0.45 * w_dr) * clamp_float(punch_scale, 0.0, 1.5),
            0.0,
            1.0,
        )
    else:
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

    negative_rgb_pct = float(np.mean(np.min(rgb, axis=1) < -GAMUT_EPS) * 100.0)
    over_rgb_pct = float(np.mean(np.max(rgb, axis=1) > 1.0 + GAMUT_EPS) * 100.0)
    # The public default follows darktable smooth geometry and preserve_hue=0.6.
    # The three Blender-reference geometries retain Blender's 0.4 hue mix so their
    # comparison remains a coherent alternate reference rather than a hybrid preset.
    hue_keep = 0.4 if agx_primaries in ("base", "punchy", "muted") else 0.6

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
        chroma_p95=chroma_p95,
        negative_rgb_pct=negative_rgb_pct,
        over_rgb_pct=over_rgb_pct,
        tone_core=tone_core,
        lum_norm=lum_norm,
        pivot_ev_offset=pivot_ev_offset,
        target_black_linear=target_black_linear,
        target_white_linear=1.0,
        agx_primaries=agx_primaries,
        hue_keep=hue_keep,
        toe_start_ev=toe_start_ev,
        shoulder_start_ev=shoulder_start_ev,
        use_c1_endpoints=True,
        view_brightness=view_brightness,
    )


def build_render_plan(
    bundle: RawBundle,
    analysis: Analysis,
    mode: str,
    output_gamut: str = "srgb",
    scene_transform: str = "none",
    scene_transform_strength: float = 1.0,
    punch_scale: float = 1.0,
    tone_core: str = "agx",
    lum_norm: str = "y",
    agx_primaries: str = "smooth",
) -> RenderPlan:
    """Compile independent scene, tone and colour plans from an immutable capture."""
    tone_core = tone_core if tone_core in TONE_CORE_CHOICES else "agx"
    lum_norm = lum_norm if lum_norm in LUM_NORM_CHOICES else "y"
    agx_primaries = agx_engine.resolve_agx_primaries(agx_primaries)
    if tone_core == "gated":
        from .guidance import ensure_raw_guidance

        ensure_raw_guidance(bundle, analysis)
    # agx / lum / neutral all curve (or pass through) in the Rec.2020 working space; the
    # `else` stays a defensive fallback for any future output-space-native core.
    if mode == "agx" or tone_core in ("lum", "neutral", "gated"):
        target_gamut = "Rec2020"
    else:
        target_gamut = output_gamut_space(output_gamut)
    plan_gain = compute_exposure_gain(exposure_mode_for_tone_core(tone_core), 0.0)
    scene = scene_tone_metrics(
        bundle, analysis, scene_transform if mode == "agx" else "none",
        scene_transform_strength, plan_gain,
    )
    tone = build_tone_compression_plan(
        bundle,
        analysis,
        target_gamut,
        ev_from_agx_inset=False,
        scene_transform=scene_transform if mode == "agx" else "none",
        scene_transform_strength=scene_transform_strength,
        punch_scale=punch_scale if mode == "agx" else 0.0,
        tone_core=tone_core,
        lum_norm=lum_norm,
        # RAW-gated rendering is deliberately tied to darktable's smooth geometry.
        # Blender-family primaries are explicit reference variants for the full-frame
        # AgX core only; they must not silently define the RAW evidence path.
        agx_primaries=agx_primaries if mode == "agx" and tone_core == "agx" else "smooth",
        plan_exposure_gain=plan_gain,
        scene_metrics=scene,
    )
    return RenderPlan(
        tone=tone,
        color=build_color_geometry_plan(analysis, output_gamut, tone_core),
        scene=scene,
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
    agx_primaries: str = "smooth",
) -> ToneCompressionPlan:
    """Compatibility accessor for callers that only need the tone sub-plan."""
    return build_render_plan(
        bundle,
        analysis,
        mode,
        output_gamut,
        scene_transform,
        scene_transform_strength,
        punch_scale,
        tone_core,
        lum_norm,
        agx_primaries,
    ).tone
