# SPDX-License-Identifier: GPL-3.0-or-later
"""Scene-linear to display-linear tone mapping pipelines."""
from __future__ import annotations

from typing import Any

from ._deps import np
from . import agx as agx_engine
from . import display_filter as filter_engine
from . import look as look_engine
from . import punch as punch_engine
from . import scene_transform as scene_transform_engine
from .color import (
    fit_to_output_gamut, luminance_from_rgb_space, oklab_to_output_rgb, rec2020_to_output,
    rgb_to_oklab, smoothstep, srgb_encode,
)
from .constants import AGX_INSET, AGX_OUTSET
from .models import Analysis, RawBundle, ToneCompressionPlan
from .tone import plan_for_mode, scene_rec2020_to_float

def dither_quantize_u8(encoded: Any, rng: Any) -> Any:
    """Quantize display-domain [0,1] floats to uint8 with 1-LSB TPDF dither."""
    scaled = encoded.astype(np.float32, copy=False) * np.float32(255.0)
    noise = rng.random(scaled.shape, dtype=np.float32) - rng.random(scaled.shape, dtype=np.float32)
    return np.clip(np.floor(scaled + np.float32(0.5) + noise), 0, 255).astype(np.uint8)


def output_linear_to_u8(
    rgb_linear: Any, output_gamut: str = "srgb", look: str = "none", look_strength: float = 1.0
) -> Any:
    return quantize_final_output_linear_to_u8(
        finalize_output_linear(rgb_linear, output_gamut, look, look_strength)
    )


def quantize_final_output_linear_to_u8(rgb_linear: Any) -> Any:
    """Encode already-finalized display-linear RGB to 8-bit JPEG code values."""
    flat = rgb_linear.reshape(-1, 3)
    out = np.empty((flat.shape[0], 3), dtype=np.uint8)
    rng = np.random.default_rng(0)
    chunk = 1_000_000
    for start in range(0, flat.shape[0], chunk):
        end = min(start + chunk, flat.shape[0])
        fitted = np.nan_to_num(flat[start:end].astype(np.float32, copy=False), nan=0.0, posinf=1.0, neginf=0.0)
        encoded = srgb_encode(fitted)
        out[start:end] = dither_quantize_u8(encoded, rng)
    return out.reshape(rgb_linear.shape[:2] + (3,))


def finalize_output_linear(
    rgb_linear: Any, output_gamut: str = "srgb", look: str = "none", look_strength: float = 1.0
) -> Any:
    """Apply the post-AgX chromatic look and output-gamut fit in display-linear RGB."""
    original_shape = rgb_linear.shape
    flat = rgb_linear.reshape(-1, 3)
    out = np.empty((flat.shape[0], 3), dtype=np.float32)
    chunk = 1_000_000
    for start in range(0, flat.shape[0], chunk):
        end = min(start + chunk, flat.shape[0])
        piece = np.nan_to_num(flat[start:end].astype(np.float32, copy=False), nan=0.0, posinf=1e6, neginf=-1e6)
        if look != "none":
            # Chromatic look layer (measured ARRI/Fujifilm geometry field) in Oklab, before
            # gamut fit so its result is still brought in-gamut hue-preservingly.
            lab_l, lab_a, lab_b = rgb_to_oklab(piece, output_gamut)
            lab_l, lab_a, lab_b = look_engine.apply_look_oklab(lab_l, lab_a, lab_b, look, look_strength)
            piece = oklab_to_output_rgb(lab_l, lab_a, lab_b, output_gamut)
        # Oklab hue-preserving gamut fit replaces per-channel clipping for every mode.
        out[start:end] = fit_to_output_gamut(piece, output_gamut).astype(np.float32, copy=False)
    return out.reshape(original_shape)


def agx_compress_into_gamut(rgb: Any) -> Any:
    return agx_engine.compress_into_gamut(rgb)


def apply_agx_core(rgb_rec2020: Any, plan: ToneCompressionPlan) -> Any:
    """AgX in Rec.2020 working space: inset -> log2 -> sigmoid curve -> outset -> gamma.

    The inset/outset channel crosstalk is what makes this AgX rather than a per-channel
    filmic curve; the darktable-derived sigmoid supplies the curve shape, while the plan's
    black/white EV keep the log2 window anchored on the exposure we set.
    """
    mapped = agx_engine.apply_core(rgb_rec2020, plan, AGX_INSET, AGX_OUTSET)
    # Scene-driven purity compensation (dngscan/punch.py). This wrapper is the single
    # convergence point for the main render AND the auto-EV probe path, so both see the
    # same transform; the look-field extractor calls agx_engine.apply_core directly and
    # stays punch-free by construction. strength 0 short-circuits to identity.
    return punch_engine.apply_punch_rec2020(mapped, float(getattr(plan, "punch_strength", 0.0)))


def scene_render_to_agx_linear(
    bundle: RawBundle,
    plan: ToneCompressionPlan,
    output_gamut: str = "srgb",
    display_filter: str = "none",
    filter_strength: float = 1.0,
    scene_transform: str = "none",
    scene_transform_strength: float = 1.0,
) -> Any:
    scene = bundle.scene_rec2020_render
    h, w = scene.shape[:2]
    flat_scene = scene.reshape(-1, scene.shape[-1])
    out = np.empty((flat_scene.shape[0], 3), dtype=np.float32)
    chunk = 1_000_000

    wb_adapt = scene_transform_engine.wb_adaptation_ratios(
        bundle.wb_mode, bundle.camera_wb, bundle.daylight_wb
    )
    for start in range(0, flat_scene.shape[0], chunk):
        end = min(start + chunk, flat_scene.shape[0])
        rec = scene_rec2020_to_float(flat_scene[start:end, :3], bundle.scene_scale, bundle.exposure_gain)
        rec = scene_transform_engine.apply_scene_transform_rec2020(
            rec, scene_transform, scene_transform_strength, wb_adapt
        )
        mapped_rec = apply_agx_core(rec, plan)
        if display_filter != "none" and filter_strength > 0.0:
            output_linear = filter_engine.apply_display_filter_rec2020(
                mapped_rec, output_gamut, display_filter, filter_strength, scene_rec2020=rec
            )
        else:
            output_linear = rec2020_to_output(mapped_rec, output_gamut)
        output_linear = np.nan_to_num(output_linear, nan=0.0, posinf=1e6, neginf=-1e6)
        out[start:end] = output_linear.astype(np.float32, copy=False)
    return out.reshape(h, w, 3)


def scene_render_to_agx_u8(
    bundle: RawBundle,
    plan: ToneCompressionPlan,
    output_gamut: str = "srgb",
    look: str = "none",
    look_strength: float = 1.0,
    display_filter: str = "none",
    filter_strength: float = 1.0,
    scene_transform: str = "none",
    scene_transform_strength: float = 1.0,
) -> Any:
    return output_linear_to_u8(
        scene_render_to_agx_linear(
            bundle,
            plan,
            output_gamut,
            display_filter,
            filter_strength,
            scene_transform,
            scene_transform_strength,
        ),
        output_gamut,
        look,
        look_strength,
    )


def render_output_linear(
    bundle: RawBundle,
    analysis: Analysis | None,
    output_gamut: str = "srgb",
    tone_plan: ToneCompressionPlan | None = None,
    look: str = "none",
    look_strength: float = 1.0,
    display_filter: str = "none",
    filter_strength: float = 1.0,
    scene_transform: str = "none",
    scene_transform_strength: float = 1.0,
) -> Any:
    if look != "none" and display_filter != "none":
        raise ValueError("色度 look 与输出滤镜不能同时启用")
    if analysis is None:
        raise ValueError("AgX 导出需要分析结果")
    plan = tone_plan if tone_plan is not None else plan_for_mode(
        bundle, analysis, "agx", output_gamut, scene_transform, scene_transform_strength
    )
    agx_linear = scene_render_to_agx_linear(
        bundle,
        plan,
        output_gamut,
        display_filter,
        filter_strength,
        scene_transform,
        scene_transform_strength,
    )
    return finalize_output_linear(agx_linear, output_gamut, look, look_strength)


def render_output_u8(
    bundle: RawBundle,
    analysis: Analysis | None,
    output_gamut: str = "srgb",
    tone_plan: ToneCompressionPlan | None = None,
    look: str = "none",
    look_strength: float = 1.0,
    display_filter: str = "none",
    filter_strength: float = 1.0,
    scene_transform: str = "none",
    scene_transform_strength: float = 1.0,
) -> Any:
    if look != "none" and display_filter != "none":
        raise ValueError("色度 look 与输出滤镜不能同时启用")
    if analysis is None:
        raise ValueError("AgX 导出需要分析结果")
    plan = tone_plan if tone_plan is not None else plan_for_mode(
        bundle, analysis, "agx", output_gamut, scene_transform, scene_transform_strength
    )
    return quantize_final_output_linear_to_u8(
        render_output_linear(
            bundle,
            analysis,
            output_gamut,
            plan,
            look,
            look_strength,
            display_filter,
            filter_strength,
            scene_transform,
            scene_transform_strength,
        ),
    )


def scene_render_to_reference_linear(bundle: RawBundle, output_gamut: str = "p3") -> Any:
    """Unclipped scene-linear output-space reference used as the HDR reservoir."""
    return scene_render_to_neutral_linear(bundle, output_gamut)


def hdr_highlight_weight(sdr_base_linear: Any, hdr_reference_linear: Any, output_gamut: str) -> Any:
    base_y = luminance_from_rgb_space(np.clip(sdr_base_linear.reshape(-1, 3), 0.0, 1.0), output_gamut)
    ref_y = luminance_from_rgb_space(np.clip(hdr_reference_linear.reshape(-1, 3), 0.0, None), output_gamut)
    base_y = np.nan_to_num(base_y, nan=0.0, posinf=1.0, neginf=0.0)
    ref_y = np.nan_to_num(ref_y, nan=0.0, posinf=1e6, neginf=0.0)
    bright = smoothstep(np.float32(0.55), np.float32(0.98), base_y)
    extra = smoothstep(np.float32(0.02), np.float32(0.50), np.maximum(ref_y - base_y, 0.0))
    ref_bright = smoothstep(np.float32(0.70), np.float32(1.20), ref_y)
    return np.maximum(bright, extra * ref_bright).reshape(sdr_base_linear.shape[:2])


def render_hdr_numerator_linear(
    bundle: RawBundle,
    sdr_linear: Any,
    output_gamut: str,
    hdr_headroom: float,
) -> Any:
    hdr_limit = np.float32(2.0 ** hdr_headroom)
    sdr_base = np.clip(np.nan_to_num(sdr_linear, nan=0.0, posinf=1.0, neginf=0.0), 0.0, 1.0)
    reference = np.clip(
        np.nan_to_num(scene_render_to_reference_linear(bundle, output_gamut), nan=0.0, posinf=float(hdr_limit), neginf=0.0),
        0.0,
        float(hdr_limit),
    )
    candidate = np.maximum(reference, sdr_base)
    weight = hdr_highlight_weight(sdr_base, reference, output_gamut).astype(np.float32, copy=False)
    hdr = sdr_base + weight[:, :, None] * (candidate - sdr_base)
    return np.maximum(sdr_base, np.clip(hdr, 0.0, float(hdr_limit))).astype(np.float32, copy=False)
