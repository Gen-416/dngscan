# SPDX-License-Identifier: GPL-3.0-or-later
"""Scene-linear to display-linear tone mapping pipelines."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ._deps import np
from . import agx as agx_engine
from . import display_filter as filter_engine
from . import look as look_engine
from .color import (
    apply_rgb_matrix3, fit_to_output_gamut, luminance_from_rec2020, luminance_from_rgb_space,
    oklab_to_output_rgb, rec2020_to_output, rec2020_to_srgb, rgb_to_oklab, smoothstep,
    srgb_encode, srgb_to_output,
)
from .constants import AGX_INSET, AGX_OUTSET, EPS, TONY_LUT_CACHE
from .models import Analysis, RawBundle, ToneCompressionPlan
from .tone import (
    compress_linear_output_rgb_for_jpeg, plan_for_mode, precondition_tonemapper_rgb,
    scene_rec2020_to_float,
)

def dither_quantize_u8(encoded: Any, rng: Any) -> Any:
    """Quantize display-domain [0,1] floats to uint8 with 1-LSB TPDF dither."""
    scaled = encoded.astype(np.float32, copy=False) * np.float32(255.0)
    noise = rng.random(scaled.shape, dtype=np.float32) - rng.random(scaled.shape, dtype=np.float32)
    return np.clip(np.floor(scaled + np.float32(0.5) + noise), 0, 255).astype(np.uint8)


def output_linear_to_u8(
    rgb_linear: Any, output_gamut: str = "srgb", look: str = "none", look_strength: float = 1.0
) -> Any:
    flat = rgb_linear.reshape(-1, 3)
    out = np.empty((flat.shape[0], 3), dtype=np.uint8)
    rng = np.random.default_rng(0)
    chunk = 1_000_000
    for start in range(0, flat.shape[0], chunk):
        end = min(start + chunk, flat.shape[0])
        piece = flat[start:end]
        if look != "none":
            # Chromatic look layer (measured ARRI-geometry field) in Oklab, before the
            # gamut fit so its result is still brought in-gamut hue-preservingly.
            piece = np.nan_to_num(piece.astype(np.float32, copy=False), nan=0.0, posinf=1e6, neginf=-1e6)
            lab_l, lab_a, lab_b = rgb_to_oklab(piece, output_gamut)
            lab_l, lab_a, lab_b = look_engine.apply_look_oklab(lab_l, lab_a, lab_b, look, look_strength)
            piece = oklab_to_output_rgb(lab_l, lab_a, lab_b, output_gamut)
        # Oklab hue-preserving gamut fit replaces per-channel clipping for every mode.
        fitted = fit_to_output_gamut(piece, output_gamut)
        encoded = srgb_encode(fitted)
        out[start:end] = dither_quantize_u8(encoded, rng)
    return out.reshape(rgb_linear.shape[:2] + (3,))


def scene_render_to_neutral_linear(bundle: RawBundle, output_gamut: str = "srgb") -> Any:
    scene = bundle.scene_rec2020_render
    h, w = scene.shape[:2]
    flat_scene = scene.reshape(-1, scene.shape[-1])
    out = np.empty((flat_scene.shape[0], 3), dtype=np.float32)
    chunk = 1_000_000

    for start in range(0, flat_scene.shape[0], chunk):
        end = min(start + chunk, flat_scene.shape[0])
        rec = scene_rec2020_to_float(flat_scene[start:end, :3], bundle.scene_scale, bundle.exposure_gain)
        output_linear = rec2020_to_output(rec, output_gamut)
        output_linear = np.nan_to_num(output_linear, nan=0.0, posinf=1e6, neginf=-1e6)
        out[start:end] = output_linear.astype(np.float32, copy=False)

    return out.reshape(h, w, 3)


def scene_render_to_neutral_u8(bundle: RawBundle, output_gamut: str = "srgb") -> Any:
    return output_linear_to_u8(scene_render_to_neutral_linear(bundle, output_gamut), output_gamut)


def scene_render_to_smart_linear(
    bundle: RawBundle, analysis: Analysis, plan: ToneCompressionPlan, output_gamut: str = "srgb"
) -> Any:
    scene = bundle.scene_rec2020_render
    h, w = scene.shape[:2]
    flat_scene = scene.reshape(-1, scene.shape[-1])
    out = np.empty((flat_scene.shape[0], 3), dtype=np.float32)
    chunk = 1_000_000

    for start in range(0, flat_scene.shape[0], chunk):
        end = min(start + chunk, flat_scene.shape[0])
        rec = scene_rec2020_to_float(flat_scene[start:end, :3], bundle.scene_scale, bundle.exposure_gain)
        output_linear = rec2020_to_output(rec, output_gamut)
        output_linear = compress_linear_output_rgb_for_jpeg(output_linear, analysis, plan, output_gamut)
        out[start:end] = output_linear.astype(np.float32, copy=False)

    return out.reshape(h, w, 3)


def scene_render_to_smart_u8(
    bundle: RawBundle, analysis: Analysis, plan: ToneCompressionPlan, output_gamut: str = "srgb"
) -> Any:
    return output_linear_to_u8(scene_render_to_smart_linear(bundle, analysis, plan, output_gamut), output_gamut)


def agx_compress_into_gamut(rgb: Any) -> Any:
    return agx_engine.compress_into_gamut(rgb)


def apply_agx_core(rgb_rec2020: Any, plan: ToneCompressionPlan) -> Any:
    """AgX in Rec.2020 working space: inset -> log2 -> sigmoid curve -> outset -> gamma.

    The inset/outset channel crosstalk is what makes this AgX rather than a per-channel
    filmic curve; the darktable-derived sigmoid supplies the curve shape, while the plan's
    black/white EV keep the log2 window anchored on the exposure we set.
    """
    return agx_engine.apply_core(rgb_rec2020, plan, AGX_INSET, AGX_OUTSET)


def scene_render_to_agx_linear(
    bundle: RawBundle,
    plan: ToneCompressionPlan,
    output_gamut: str = "srgb",
    display_filter: str = "none",
    filter_strength: float = 1.0,
) -> Any:
    scene = bundle.scene_rec2020_render
    h, w = scene.shape[:2]
    flat_scene = scene.reshape(-1, scene.shape[-1])
    out = np.empty((flat_scene.shape[0], 3), dtype=np.float32)
    chunk = 1_000_000

    for start in range(0, flat_scene.shape[0], chunk):
        end = min(start + chunk, flat_scene.shape[0])
        rec = scene_rec2020_to_float(flat_scene[start:end, :3], bundle.scene_scale, bundle.exposure_gain)
        mapped_rec = apply_agx_core(rec, plan)
        if display_filter != "none" and filter_strength > 0.0:
            output_linear = filter_engine.apply_display_filter_rec2020(
                mapped_rec, output_gamut, display_filter, filter_strength
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
) -> Any:
    return output_linear_to_u8(
        scene_render_to_agx_linear(bundle, plan, output_gamut, display_filter, filter_strength),
        output_gamut,
        look,
        look_strength,
    )


def default_tony_lut_path() -> Path:
    return Path(__file__).resolve().parents[1] / "dngscan_assets" / "tony_mc_mapface.spi3d"


def load_tony_spi3d(path: Path) -> Any:
    path = path.expanduser()
    if not path.exists():
        raise FileNotFoundError(
            f"Tony LUT not found: {path}. Download tony_mc_mapface.spi3d from "
            "https://github.com/h3r2tic/tony-mc-mapface/tree/main/OCIO/LUTs or pass --tony-lut."
        )
    stat = path.stat()
    key = (str(path.resolve()), int(stat.st_mtime_ns), int(stat.st_size))
    cached = TONY_LUT_CACHE.get(key)
    if cached is not None:
        return cached
    entries: list[tuple[int, int, int, float, float, float]] = []
    dims: tuple[int, int, int] | None = None
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("SPILUT") or stripped == "3 3":
                continue
            parts = stripped.split()
            if len(parts) == 3 and dims is None:
                dims = (int(parts[0]), int(parts[1]), int(parts[2]))
                continue
            if len(parts) >= 6:
                entries.append(
                    (int(parts[0]), int(parts[1]), int(parts[2]), float(parts[3]), float(parts[4]), float(parts[5]))
                )
    if dims is None:
        raise RuntimeError(f"Cannot parse Tony LUT dimensions from {path}")
    nr, ng, nb = dims
    expected = nr * ng * nb
    if len(entries) != expected:
        raise RuntimeError(f"Tony LUT size mismatch: expected {expected}, got {len(entries)}")
    # Place each sample by its explicit (r, g, b) index columns rather than assuming row
    # order; this keeps the R and B axes from being transposed. lut is indexed [r, g, b]
    # so sample_tony_lut's channel-0->R mapping is correct.
    lut = np.empty((nr, ng, nb, 3), dtype=np.float32)
    filled = np.zeros((nr, ng, nb), dtype=bool)
    for ri, gi, bi, ro, go, bo in entries:
        if not (0 <= ri < nr and 0 <= gi < ng and 0 <= bi < nb):
            raise RuntimeError(f"Tony LUT index {(ri, gi, bi)} out of range for dims {dims}")
        lut[ri, gi, bi] = (ro, go, bo)
        filled[ri, gi, bi] = True
    if not bool(filled.all()):
        raise RuntimeError(f"Tony LUT is missing {int((~filled).sum())} grid points; file may be truncated")
    TONY_LUT_CACHE.clear()
    TONY_LUT_CACHE[key] = lut
    return lut


def sample_tony_lut(rgb: Any, lut: Any) -> Any:
    dims = lut.shape[0]
    stimulus = np.clip(rgb.astype(np.float32, copy=False), 0.0, None)
    coords = (stimulus / (stimulus + 1.0)) * float(dims - 1)
    coords = np.clip(coords, 0.0, float(dims - 1))
    lo = np.floor(coords).astype(np.int32)
    hi = np.minimum(lo + 1, dims - 1)
    frac = coords - lo
    x0, y0, z0 = lo[:, 0], lo[:, 1], lo[:, 2]
    x1, y1, z1 = hi[:, 0], hi[:, 1], hi[:, 2]
    fx, fy, fz = frac[:, 0:1], frac[:, 1:2], frac[:, 2:3]
    c000 = lut[x0, y0, z0]
    c100 = lut[x1, y0, z0]
    c010 = lut[x0, y1, z0]
    c110 = lut[x1, y1, z0]
    c001 = lut[x0, y0, z1]
    c101 = lut[x1, y0, z1]
    c011 = lut[x0, y1, z1]
    c111 = lut[x1, y1, z1]
    c00 = c000 * (1.0 - fx) + c100 * fx
    c10 = c010 * (1.0 - fx) + c110 * fx
    c01 = c001 * (1.0 - fx) + c101 * fx
    c11 = c011 * (1.0 - fx) + c111 * fx
    c0 = c00 * (1.0 - fy) + c10 * fy
    c1 = c01 * (1.0 - fy) + c11 * fy
    return c0 * (1.0 - fz) + c1 * fz


def scene_render_to_tony_linear(
    bundle: RawBundle, plan: ToneCompressionPlan, lut_path: Path, output_gamut: str = "srgb"
) -> Any:
    lut = load_tony_spi3d(lut_path)
    scene = bundle.scene_rec2020_render
    h, w = scene.shape[:2]
    flat_scene = scene.reshape(-1, scene.shape[-1])
    out = np.empty((flat_scene.shape[0], 3), dtype=np.float32)
    chunk = 1_000_000
    for start in range(0, flat_scene.shape[0], chunk):
        end = min(start + chunk, flat_scene.shape[0])
        rec = scene_rec2020_to_float(flat_scene[start:end, :3], bundle.scene_scale, bundle.exposure_gain)
        y = luminance_from_rec2020(rec)
        srgb_linear = rec2020_to_srgb(rec)
        srgb_linear = precondition_tonemapper_rgb(srgb_linear, y, plan, for_tony=True)
        mapped_linear = sample_tony_lut(srgb_linear, lut)
        output_linear = srgb_to_output(mapped_linear, output_gamut)
        output_linear = np.nan_to_num(output_linear, nan=0.0, posinf=1e6, neginf=-1e6)
        out[start:end] = output_linear.astype(np.float32, copy=False)
    return out.reshape(h, w, 3)


def scene_render_to_tony_u8(
    bundle: RawBundle, plan: ToneCompressionPlan, lut_path: Path, output_gamut: str = "srgb"
) -> Any:
    return output_linear_to_u8(scene_render_to_tony_linear(bundle, plan, lut_path, output_gamut), output_gamut)


def scene_render_to_output_linear(
    bundle: RawBundle,
    analysis: Analysis,
    mode: str,
    output_gamut: str = "srgb",
    tony_lut_path: Path | None = None,
    tone_plan: ToneCompressionPlan | None = None,
) -> Any:
    if mode == "smart":
        plan = tone_plan if tone_plan is not None else plan_for_mode(bundle, analysis, mode, output_gamut)
        return scene_render_to_smart_linear(bundle, analysis, plan, output_gamut)
    if mode == "agx":
        plan = tone_plan if tone_plan is not None else plan_for_mode(bundle, analysis, mode, output_gamut)
        return scene_render_to_agx_linear(bundle, plan, output_gamut)
    if mode == "tony":
        plan = tone_plan if tone_plan is not None else plan_for_mode(bundle, analysis, mode, output_gamut)
        lut_path = tony_lut_path if tony_lut_path is not None else default_tony_lut_path()
        return scene_render_to_tony_linear(bundle, plan, lut_path, output_gamut)
    return scene_render_to_neutral_linear(bundle, output_gamut)


def render_output_u8(
    bundle: RawBundle,
    analysis: Analysis | None,
    output_gamut: str = "srgb",
    tone_plan: ToneCompressionPlan | None = None,
    look: str = "none",
    look_strength: float = 1.0,
    display_filter: str = "none",
    filter_strength: float = 1.0,
) -> Any:
    if look != "none" and display_filter != "none":
        raise ValueError("色度 look 与输出滤镜不能同时启用")
    if analysis is None:
        raise ValueError("AgX 导出需要分析结果")
    plan = tone_plan if tone_plan is not None else plan_for_mode(bundle, analysis, "agx", output_gamut)
    return scene_render_to_agx_u8(
        bundle, plan, output_gamut, look, look_strength, display_filter, filter_strength
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

