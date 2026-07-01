#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
#
# The AgX JPEG mode ports portions of darktable's GPL-3.0-or-later AgX
# implementation. Tony McMapface assets are external and dual-licensed under
# Apache-2.0 OR MIT by h3r2tic/tony-mc-mapface.
from __future__ import annotations

import argparse
import csv
import math
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

IMPORT_ERRORS: list[str] = []

try:
    import numpy as np
except Exception as exc:  # pragma: no cover - exercised only on missing deps
    np = None  # type: ignore[assignment]
    IMPORT_ERRORS.append(f"numpy: {exc}")

try:
    import rawpy
except Exception as exc:  # pragma: no cover - exercised only on missing deps
    rawpy = None  # type: ignore[assignment]
    IMPORT_ERRORS.append(f"rawpy: {exc}")

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.image as mpimg
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    from matplotlib.colors import ListedColormap
    from matplotlib.patches import Patch
except Exception as exc:  # pragma: no cover - exercised only on missing deps
    matplotlib = None  # type: ignore[assignment]
    mpimg = None  # type: ignore[assignment]
    plt = None  # type: ignore[assignment]
    font_manager = None  # type: ignore[assignment]
    ListedColormap = None  # type: ignore[assignment]
    Patch = None  # type: ignore[assignment]
    IMPORT_ERRORS.append(f"matplotlib: {exc}")


EPS = 1e-12
GAMUT_EPS = 1e-3
EV_REPORT_FLOOR = -14.0
GRAY_EV = math.log2(0.18)
MIDGRAY_HEADROOM_STOPS = 3.0
NOISE_DR_EPS = 1e-9
SNR_TILE = 16
SNR_LOW_PERCENTILE = 20.0
SNR_BRIGHT_UNRELIABLE_STOP = -2.5
CEILING_MIN_PILE_PIXELS = 256
CEILING_MIN_PILE_FRACTION = 2e-5
OUTPUT_GAMUT_SPACES = {"srgb": "sRGB", "p3": "P3"}
OUTPUT_GAMUT_LABELS = {"srgb": "sRGB", "p3": "Display P3"}

XYZ_TO_RGB = {
    "sRGB": np.array(  # type: ignore[union-attr]
        [[3.2406, -1.5372, -0.4986], [-0.9689, 1.8758, 0.0415], [0.0557, -0.2040, 1.0570]],
        dtype=np.float64,
    )
    if np is not None
    else None,
    "P3": np.array(  # type: ignore[union-attr]
        [[2.4934, -0.9314, -0.4027], [-0.8295, 1.7627, 0.0236], [0.0358, -0.0762, 0.9569]],
        dtype=np.float64,
    )
    if np is not None
    else None,
    "Rec2020": np.array(  # type: ignore[union-attr]
        [[1.7167, -0.3557, -0.2534], [-0.6667, 1.6165, 0.0158], [0.0176, -0.0428, 0.9421]],
        dtype=np.float64,
    )
    if np is not None
    else None,
}

RGB_TO_XYZ = {
    name: np.linalg.inv(matrix).astype(np.float64) if np is not None and matrix is not None else None
    for name, matrix in XYZ_TO_RGB.items()
}

REC2020_TO_SRGB = (
    (XYZ_TO_RGB["sRGB"] @ RGB_TO_XYZ["Rec2020"]).astype(np.float64)
    if np is not None
    else None
)
SRGB_TO_REC2020 = (
    (XYZ_TO_RGB["Rec2020"] @ RGB_TO_XYZ["sRGB"]).astype(np.float64)
    if np is not None
    else None
)

# Reference AgX inset/outset from Troy Sobotka's AgX family, expressed for
# sRGB/Rec.709 primaries. We map this reference transform into Rec.2020 below so
# the script can keep the AgX view transform in the same wide scene-linear space
# used by the RAW export buffer.
AGX_REFERENCE_INSET = (
    np.array(  # type: ignore[union-attr]
        [
            [0.842479062253094, 0.0784335999999992, 0.0792237451477643],
            [0.0423282422610123, 0.878468636469772, 0.0791661274605434],
            [0.0423756549057051, 0.0784336, 0.879142973793104],
        ],
        dtype=np.float64,
    )
    if np is not None
    else None
)

AGX_INSET = (
    (SRGB_TO_REC2020 @ AGX_REFERENCE_INSET @ REC2020_TO_SRGB).astype(np.float64)
    if np is not None
    else None
)
if np is not None and AGX_INSET is not None:
    AGX_INSET = (AGX_INSET / AGX_INSET.sum(axis=1, keepdims=True)).astype(np.float64)
AGX_OUTSET = (
    np.linalg.inv(AGX_INSET).astype(np.float64) if np is not None and AGX_INSET is not None else None
)


@dataclass
class RawBundle:
    path: Path
    raw_image: Any
    raw_colors: Any
    xyz_render: Any
    render_scale: float
    scene_rec2020_render: Any
    scene_scale: float
    white_level: int
    black_levels: list[float]
    camera_wb: list[float]
    color_desc: str
    raw_pattern: list[list[int]]
    camera_white_levels: list[float]
    scene_highlight_mode: str = "clip"
    orientation_flip: int = 0
    exposure_gain: float = 1.0


@dataclass
class Analysis:
    channel_ids: list[int]
    labels: dict[int, str]
    ceilings: dict[int, int]
    ceil_spike_counts: dict[int, int]
    ceil_near_counts: dict[int, int]
    ceil_spike_ok: dict[int, bool]
    fullwell_channel_ids: list[int]
    fullwell_note: str
    saturation_levels: dict[int, int]
    channel_fullwell: dict[int, int]
    channel_thresholds: dict[int, int]
    fullwell: int
    threshold: int
    clip_pct: dict[int, float]
    cfa_cell_supported: bool
    cell_union_pct: float
    cell_ge2_of_clipped_pct: float
    cell_k_of_clipped_pct: dict[int, float]
    cell_k_of_all_pct: dict[int, float]
    ev_p1: float
    ev_raw_p1: float
    ev_median: float
    ev_p99: float
    ev_p999: float
    ev_dr_p1_p999: float
    ev_floor_hit_pct: float
    median_vs_gray_ev: float
    median_y: float
    noise_floor: float
    usable_dr_ev: float
    snr_curves: dict[str, dict[str, Any]]
    snr1_dr: dict[str, float]
    snr1_stop: dict[str, float]
    gamut_out_pct: dict[str, float]
    bright_pixel_pct: float
    survivor_channel: str
    container_bits_est: int


@dataclass
class ToneCompressionPlan:
    target_gamut: str
    luma_p1: float
    luma_p50: float
    luma_p99: float
    luma_p999: float
    black_ev: float
    white_ev: float
    dynamic_range_ev: float
    contrast: float
    toe_power: float
    shoulder_power: float
    chroma_strength: float
    chroma_p95: float
    negative_rgb_pct: float
    over_rgb_pct: float
    tony_hdr_gain: float


def require_dependencies() -> None:
    if IMPORT_ERRORS:
        joined = "\n  ".join(IMPORT_ERRORS)
        raise RuntimeError(
            "Missing or broken dependency. Install only the required packages "
            "(rawpy, numpy, matplotlib) and rerun.\n  " + joined
        )


def configure_plot_fonts() -> None:
    if plt is None or font_manager is None:
        return
    candidates = [
        "PingFang SC",
        "Hiragino Sans GB",
        "Heiti SC",
        "Songti SC",
        "STHeiti",
        "Arial Unicode MS",
        "Noto Sans CJK SC",
        "Source Han Sans SC",
        "Microsoft YaHei",
        "SimHei",
    ]
    available = {font.name for font in font_manager.fontManager.ttflist}
    chosen = next((name for name in candidates if name in available), None)
    if chosen:
        plt.rcParams["font.family"] = "sans-serif"
        plt.rcParams["font.sans-serif"] = [chosen, "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="分析 RAW/DNG 传感器数据，并输出六面板诊断 PNG。"
    )
    parser.add_argument("path", type=Path, help="RAW/DNG 文件路径")
    parser.add_argument(
        "--margin",
        type=int,
        default=4,
        help="每通道满阱剪切阈值的 DN 回退量 (默认: 4)",
    )
    parser.add_argument(
        "--scan",
        action="store_true",
        help="导出六面板诊断 PNG；纯 JPEG 转换默认不画图",
    )
    parser.add_argument("--out", type=Path, default=None, help="诊断 PNG 输出路径；设置后隐含 --scan")
    parser.add_argument("--csv", type=Path, default=None, help="可选指标 CSV 路径")
    parser.add_argument(
        "--jpeg",
        type=Path,
        default=None,
        help="可选 8-bit sRGB JPEG 输出路径；使用相机白平衡，关闭自动增亮和曝光补偿",
    )
    parser.add_argument(
        "--jpeg-quality",
        type=int,
        default=100,
        help="JPEG 质量 1-100；默认 100，并使用 4:4:4 色度采样",
    )
    parser.add_argument(
        "--ev",
        type=float,
        default=0.0,
        help="手动曝光补偿（档），应用于 JPEG 导出；固定常数、绝不按画面内容自适应",
    )
    parser.add_argument(
        "--jpeg-mode",
        choices=("neutral", "smart", "agx", "tony"),
        default="neutral",
        help="JPEG 转码模式: neutral=忠实参考直出；smart=分析驱动压缩；agx=darktable AgX 核心曲线；tony=Tony McMapface LUT",
    )
    parser.add_argument(
        "--highlight-mode",
        choices=("clip", "blend", "reconstruct"),
        default="clip",
        help="JPEG 导出缓存的高光处理: clip=硬剪切；blend=libraw 高光混合；reconstruct=libraw 默认高光重建",
    )
    parser.add_argument(
        "--output-gamut",
        choices=("srgb", "p3"),
        default="srgb",
        help="JPEG 输出色彩空间: srgb=兼容优先；p3=Display P3 并嵌入 ICC",
    )
    parser.add_argument(
        "--tony-lut",
        type=Path,
        default=None,
        help="Tony McMapface .spi3d LUT 路径；默认查找 ~/dngscan_assets/tony_mc_mapface.spi3d",
    )
    args = parser.parse_args(argv)
    if args.margin < 0:
        parser.error("--margin must be >= 0")
    if not 1 <= args.jpeg_quality <= 100:
        parser.error("--jpeg-quality must be between 1 and 100")
    return args


def decode_color_desc(desc: Any) -> str:
    if isinstance(desc, bytes):
        text = desc.decode("ascii", errors="replace")
    else:
        text = str(desc)
    return text.replace("\x00", "").strip()


def rawpy_highlight_mode(name: str) -> Any:
    modes = getattr(rawpy, "HighlightMode", object)
    mapping = {
        "clip": getattr(modes, "Clip", 0),
        "blend": getattr(modes, "Blend", getattr(modes, "Clip", 0)),
        "reconstruct": getattr(modes, "ReconstructDefault", getattr(modes, "Clip", 0)),
    }
    if name not in mapping:
        raise ValueError(f"unknown highlight mode: {name}")
    return mapping[name]


def highlight_mode_cn(name: str) -> str:
    return {
        "clip": "硬剪切",
        "blend": "高光混合",
        "reconstruct": "高光重建",
    }.get(name, name)


def render_to_xyz(raw: Any) -> Any:
    if not hasattr(rawpy.ColorSpace, "XYZ"):
        raise RuntimeError("rawpy.ColorSpace.XYZ is not available; cannot make device-independent EV/gamut metrics")
    output_color = rawpy.ColorSpace.XYZ
    return raw.postprocess(
        output_color=output_color,
        gamma=(1, 1),
        no_auto_bright=True,
        use_camera_wb=True,
        highlight_mode=rawpy_highlight_mode("clip"),
        output_bps=16,
        user_flip=0,
    )


def render_to_scene_rec2020(raw: Any, highlight_mode_name: str = "clip", half_size: bool = False) -> Any:
    if not hasattr(rawpy.ColorSpace, "Rec2020"):
        raise RuntimeError("rawpy.ColorSpace.Rec2020 is not available; cannot make scene-linear export buffer")
    return raw.postprocess(
        output_color=rawpy.ColorSpace.Rec2020,
        gamma=(1, 1),
        half_size=half_size,
        no_auto_bright=True,
        use_camera_wb=True,
        highlight_mode=rawpy_highlight_mode(highlight_mode_name),
        output_bps=16,
        user_flip=None,
    )


def render_to_srgb8(raw: Any, highlight_mode_name: str = "clip") -> Any:
    return raw.postprocess(
        output_color=rawpy.ColorSpace.sRGB,
        gamma=(2.222, 4.5),
        no_auto_bright=True,
        use_camera_wb=True,
        highlight_mode=rawpy_highlight_mode(highlight_mode_name),
        output_bps=8,
        user_flip=None,
    )


def output_gamut_space(output_gamut: str) -> str:
    if output_gamut not in OUTPUT_GAMUT_SPACES:
        raise ValueError(f"unknown output gamut: {output_gamut}")
    return OUTPUT_GAMUT_SPACES[output_gamut]


def output_gamut_label(output_gamut: str) -> str:
    return OUTPUT_GAMUT_LABELS.get(output_gamut, output_gamut)


def read_first_existing(paths: list[Path]) -> bytes | None:
    for path in paths:
        try:
            if path.is_file():
                return path.read_bytes()
        except OSError:
            continue
    return None


def output_icc_profile_bytes(output_gamut: str) -> bytes | None:
    if output_gamut == "p3":
        profile = read_first_existing(
            [
                Path("/System/Library/ColorSync/Profiles/Display P3.icc"),
                Path("/Library/ColorSync/Profiles/Display P3.icc"),
            ]
        )
        if profile is None:
            raise RuntimeError("未找到 Display P3 ICC，无法安全导出 P3，请改用 sRGB")
        return profile
    if output_gamut != "srgb":
        raise ValueError(f"unknown output gamut: {output_gamut}")
    system_profile = read_first_existing(
        [
            Path("/System/Library/ColorSync/Profiles/sRGB Profile.icc"),
            Path("/Library/ColorSync/Profiles/sRGB Profile.icc"),
        ]
    )
    if system_profile is not None:
        return system_profile
    try:
        from PIL import ImageCms

        profile = ImageCms.createProfile("sRGB")
        return ImageCms.ImageCmsProfile(profile).tobytes()
    except Exception:
        return None


def srgb_encode(linear: Any) -> Any:
    linear = np.clip(linear, 0.0, 1.0)
    return np.where(linear <= 0.0031308, linear * 12.92, 1.055 * np.power(linear, 1.0 / 2.4) - 0.055)


def apply_rgb_matrix3(rgb: Any, matrix: Any) -> Any:
    out = np.empty((rgb.shape[0], 3), dtype=np.float32)
    out[:, 0] = matrix[0, 0] * rgb[:, 0] + matrix[0, 1] * rgb[:, 1] + matrix[0, 2] * rgb[:, 2]
    out[:, 1] = matrix[1, 0] * rgb[:, 0] + matrix[1, 1] * rgb[:, 1] + matrix[1, 2] * rgb[:, 2]
    out[:, 2] = matrix[2, 0] * rgb[:, 0] + matrix[2, 1] * rgb[:, 1] + matrix[2, 2] * rgb[:, 2]
    return out


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


def rec2020_to_xyz(rgb: Any) -> Any:
    return apply_rgb_matrix3(rgb, RGB_TO_XYZ["Rec2020"])


def rec2020_to_srgb(rgb: Any) -> Any:
    return apply_rgb_matrix3(rec2020_to_xyz(rgb), XYZ_TO_RGB["sRGB"])


def rec2020_to_output(rgb: Any, output_gamut: str) -> Any:
    return apply_rgb_matrix3(rec2020_to_xyz(rgb), XYZ_TO_RGB[output_gamut_space(output_gamut)])


def srgb_to_output(rgb: Any, output_gamut: str) -> Any:
    if output_gamut == "srgb":
        return rgb
    return apply_rgb_matrix3(apply_rgb_matrix3(rgb, RGB_TO_XYZ["sRGB"]), XYZ_TO_RGB[output_gamut_space(output_gamut)])


def luminance_from_rec2020(rgb: Any) -> Any:
    matrix = RGB_TO_XYZ["Rec2020"]
    y = (matrix[1, 0] * rgb[:, 0] + matrix[1, 1] * rgb[:, 1] + matrix[1, 2] * rgb[:, 2]).astype(
        np.float32, copy=False
    )
    return np.clip(np.nan_to_num(y, nan=0.0, posinf=1e6, neginf=0.0), 0.0, None)


def luminance_from_srgb(rgb: Any) -> Any:
    matrix = RGB_TO_XYZ["sRGB"]
    y = (matrix[1, 0] * rgb[:, 0] + matrix[1, 1] * rgb[:, 1] + matrix[1, 2] * rgb[:, 2]).astype(
        np.float32, copy=False
    )
    return np.clip(np.nan_to_num(y, nan=0.0, posinf=1e6, neginf=0.0), 0.0, None)


def luminance_from_rgb_space(rgb: Any, output_gamut: str) -> Any:
    matrix = RGB_TO_XYZ[output_gamut_space(output_gamut)]
    y = (matrix[1, 0] * rgb[:, 0] + matrix[1, 1] * rgb[:, 1] + matrix[1, 2] * rgb[:, 2]).astype(
        np.float32, copy=False
    )
    return np.clip(np.nan_to_num(y, nan=0.0, posinf=1e6, neginf=0.0), 0.0, None)


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


def clamp_float(value: float, low: float, high: float) -> float:
    return min(high, max(low, float(value)))


def smoothstep(edge0: float, edge1: float, x: Any) -> Any:
    if edge1 <= edge0 + EPS:
        return np.zeros_like(x, dtype=np.float32)
    t = np.clip((x - np.float32(edge0)) / np.float32(edge1 - edge0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


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
        inset = apply_rgb_matrix3(agx_compress_into_gamut(rec2020.astype(np.float32, copy=False)), AGX_INSET)
        inset_v = np.clip(inset.reshape(-1), 2.0 ** EV_REPORT_FLOOR, None)
        ev_ch = np.log2(inset_v) - GRAY_EV
        ev_p1, ev_p99, ev_p999 = [float(v) for v in np.percentile(ev_ch, [1.0, 99.0, 99.9])]

    max_clip = max(analysis.clip_pct.values()) if analysis.clip_pct else 0.0
    clip_term = clamp_float(max_clip / 1.0, 0.0, 1.0)
    gamut_risk = analysis.gamut_out_pct.get(target_gamut, 0.0)
    gamut_term = clamp_float(gamut_risk / 6.0, 0.0, 1.0)

    if math.isfinite(analysis.usable_dr_ev):
        noise_limited_black = -analysis.usable_dr_ev - 1.5
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
    shadow_term = clamp_float((10.0 - analysis.usable_dr_ev) / 3.0, 0.0, 1.0) if math.isfinite(analysis.usable_dr_ev) else 0.5
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
        return np.clip(rgb, 0.0, 1.0)

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

    # Fold any residual out-of-[0,1] back along the luminance-anchored axis, so clipping
    # never skews hue the way naive per-channel clamping would.
    rgb_min = np.min(rgb, axis=1)
    rgb_max = np.max(rgb, axis=1)
    clamp_scale = np.ones(rgb.shape[0], dtype=np.float32)
    high = (rgb_max > 1.0) & (rgb_max > anchor + EPS)
    if np.any(high):
        clamp_scale[high] = np.minimum(clamp_scale[high], (1.0 - anchor[high]) / (rgb_max[high] - anchor[high]))
    low = (rgb_min < 0.0) & (rgb_min < anchor - EPS)
    if np.any(low):
        clamp_scale[low] = np.minimum(clamp_scale[low], (0.0 - anchor[low]) / (rgb_min[low] - anchor[low]))
    clamp_scale = np.clip(clamp_scale, 0.0, 1.0)
    rgb = anchor[:, None] + clamp_scale[:, None] * (rgb - anchor[:, None])
    return np.clip(rgb, 0.0, 1.0)


def dither_quantize_u8(encoded: Any, rng: Any) -> Any:
    """Quantize display-domain [0,1] floats to uint8 with 1-LSB TPDF dither."""
    scaled = encoded.astype(np.float32, copy=False) * np.float32(255.0)
    noise = rng.random(scaled.shape, dtype=np.float32) - rng.random(scaled.shape, dtype=np.float32)
    return np.clip(np.floor(scaled + np.float32(0.5) + noise), 0, 255).astype(np.uint8)


def scene_render_to_neutral_u8(bundle: RawBundle, output_gamut: str = "srgb") -> Any:
    scene = bundle.scene_rec2020_render
    h, w = scene.shape[:2]
    flat_scene = scene.reshape(-1, scene.shape[-1])
    out = np.empty((flat_scene.shape[0], 3), dtype=np.uint8)
    rng = np.random.default_rng(0)
    chunk = 1_000_000

    for start in range(0, flat_scene.shape[0], chunk):
        end = min(start + chunk, flat_scene.shape[0])
        rec = scene_rec2020_to_float(flat_scene[start:end, :3], bundle.scene_scale, bundle.exposure_gain)
        output_linear = rec2020_to_output(rec, output_gamut)
        output_linear = np.nan_to_num(output_linear, nan=0.0, posinf=1e6, neginf=-1e6)
        encoded = srgb_encode(np.clip(output_linear, 0.0, 1.0))
        out[start:end] = dither_quantize_u8(encoded, rng)

    return out.reshape(h, w, 3)


def scene_render_to_smart_u8(
    bundle: RawBundle, analysis: Analysis, plan: ToneCompressionPlan, output_gamut: str = "srgb"
) -> Any:
    scene = bundle.scene_rec2020_render
    h, w = scene.shape[:2]
    flat_scene = scene.reshape(-1, scene.shape[-1])
    out = np.empty((flat_scene.shape[0], 3), dtype=np.uint8)
    rng = np.random.default_rng(0)
    chunk = 1_000_000

    for start in range(0, flat_scene.shape[0], chunk):
        end = min(start + chunk, flat_scene.shape[0])
        rec = scene_rec2020_to_float(flat_scene[start:end, :3], bundle.scene_scale, bundle.exposure_gain)
        output_linear = rec2020_to_output(rec, output_gamut)
        output_linear = compress_linear_output_rgb_for_jpeg(output_linear, analysis, plan, output_gamut)
        encoded = srgb_encode(output_linear)
        out[start:end] = dither_quantize_u8(encoded, rng)

    return out.reshape(h, w, 3)


@lru_cache(maxsize=32)
def agx_curve_params(
    black_ev: float = -10.0,
    white_ev: float = 6.5,
    contrast: float = 3.0,
    toe_power: float = 1.5,
    shoulder_power: float = 3.3,
) -> dict[str, float | bool]:
    # Derived from darktable's GPLv3 AgX implementation:
    # https://github.com/darktable-org/darktable/blob/master/src/iop/agx.c
    # and its OpenCL kernel:
    # https://github.com/darktable-org/darktable/blob/master/data/kernels/agx.cl
    default_gamma = 2.2
    black_ev = float(black_ev)
    white_ev = float(white_ev)
    range_ev = max(1.0, white_ev - black_ev)
    pivot_x = clamp_float(-black_ev / range_ev, EPS, 1.0 - EPS)
    pivot_y_linear = 0.18
    pivot_y = pivot_y_linear ** (1.0 / default_gamma)
    target_black = 0.0
    target_white = 1.0
    range_adjusted_slope = contrast * (range_ev / 16.5)
    pivot_y_default = pivot_y
    derivative_current = default_gamma * max(EPS, pivot_y) ** (default_gamma - 1.0)
    derivative_default = default_gamma * max(EPS, pivot_y_default) ** (default_gamma - 1.0)
    slope = range_adjusted_slope / (derivative_current / derivative_default)

    toe_transition_x = max(EPS, pivot_x)
    toe_transition_y = pivot_y
    inverse_toe_limit_x = 1.0
    inverse_toe_limit_y = 1.0 - target_black
    inverse_toe_transition_x = 1.0 - toe_transition_x
    inverse_toe_transition_y = 1.0 - toe_transition_y
    toe_scale = -agx_scale(
        inverse_toe_limit_x,
        inverse_toe_limit_y,
        inverse_toe_transition_x,
        inverse_toe_transition_y,
        slope,
        toe_power,
    )
    toe_length_x = toe_transition_x
    toe_dy = max(EPS, toe_transition_y - target_black)
    toe_slope_to_limit = toe_dy / toe_length_x
    need_convex_toe = toe_slope_to_limit > slope
    toe_fallback_power = slope * toe_length_x / toe_dy
    toe_fallback_coefficient = toe_dy / max(EPS, toe_length_x) ** toe_fallback_power
    intercept = toe_transition_y - slope * toe_transition_x

    shoulder_transition_x = min(1.0 - EPS, pivot_x)
    shoulder_transition_y = pivot_y
    shoulder_scale = agx_scale(1.0, target_white, shoulder_transition_x, shoulder_transition_y, slope, shoulder_power)
    shoulder_length_x = 1.0 - shoulder_transition_x
    shoulder_dy = max(EPS, target_white - shoulder_transition_y)
    shoulder_slope_to_limit = shoulder_dy / shoulder_length_x
    need_concave_shoulder = shoulder_slope_to_limit > slope
    shoulder_fallback_power = slope * shoulder_length_x / shoulder_dy
    shoulder_fallback_coefficient = shoulder_dy / max(EPS, shoulder_length_x) ** shoulder_fallback_power
    return {
        "black_ev": black_ev,
        "range_ev": range_ev,
        "gamma": default_gamma,
        "target_black": target_black,
        "target_white": target_white,
        "toe_power": toe_power,
        "toe_transition_x": toe_transition_x,
        "toe_transition_y": toe_transition_y,
        "toe_scale": toe_scale,
        "need_convex_toe": need_convex_toe,
        "toe_fallback_power": toe_fallback_power,
        "toe_fallback_coefficient": toe_fallback_coefficient,
        "slope": slope,
        "intercept": intercept,
        "shoulder_power": shoulder_power,
        "shoulder_transition_x": shoulder_transition_x,
        "shoulder_transition_y": shoulder_transition_y,
        "shoulder_scale": shoulder_scale,
        "need_concave_shoulder": need_concave_shoulder,
        "shoulder_fallback_power": shoulder_fallback_power,
        "shoulder_fallback_coefficient": shoulder_fallback_coefficient,
    }


def agx_scale(limit_x: float, limit_y: float, transition_x: float, transition_y: float, slope: float, power: float) -> float:
    projected_rise = slope * max(EPS, limit_x - transition_x)
    actual_rise = max(EPS, limit_y - transition_y)
    base = max(EPS, actual_rise ** (-power) - projected_rise ** (-power))
    return min(1e9, base ** (-1.0 / power))


def agx_sigmoid(x: Any, power: float) -> Any:
    return x / np.power(1.0 + np.power(x, power), 1.0 / power)


def agx_scaled_sigmoid(x: Any, scale: float, slope: float, power: float, transition_x: float, transition_y: float) -> Any:
    return scale * agx_sigmoid(slope * (x - transition_x) / scale, power) + transition_y


def agx_apply_curve(x: Any, params: dict[str, float | bool]) -> Any:
    x = np.asarray(x, dtype=np.float32)
    out = np.empty_like(x)
    toe = x < float(params["toe_transition_x"])
    shoulder = x > float(params["shoulder_transition_x"])
    mid = ~(toe | shoulder)
    if np.any(toe):
        if bool(params["need_convex_toe"]):
            out[toe] = float(params["target_black"]) + np.maximum(
                0.0,
                float(params["toe_fallback_coefficient"]) * np.power(np.maximum(x[toe], 0.0), float(params["toe_fallback_power"])),
            )
        else:
            out[toe] = agx_scaled_sigmoid(
                x[toe],
                float(params["toe_scale"]),
                float(params["slope"]),
                float(params["toe_power"]),
                float(params["toe_transition_x"]),
                float(params["toe_transition_y"]),
            )
    if np.any(mid):
        out[mid] = float(params["slope"]) * x[mid] + float(params["intercept"])
    if np.any(shoulder):
        if bool(params["need_concave_shoulder"]):
            out[shoulder] = float(params["target_white"]) - np.maximum(
                0.0,
                float(params["shoulder_fallback_coefficient"])
                * np.power(np.maximum(1.0 - x[shoulder], 0.0), float(params["shoulder_fallback_power"])),
            )
        else:
            out[shoulder] = agx_scaled_sigmoid(
                x[shoulder],
                float(params["shoulder_scale"]),
                float(params["slope"]),
                float(params["shoulder_power"]),
                float(params["shoulder_transition_x"]),
                float(params["shoulder_transition_y"]),
            )
    return np.clip(out, float(params["target_black"]), float(params["target_white"]))


def agx_compress_into_gamut(rgb: Any) -> Any:
    coeff = np.asarray([0.2658180370250449, 0.59846986045365, 0.1357121025213052], dtype=np.float32)
    input_y = coeff[0] * rgb[:, 0] + coeff[1] * rgb[:, 1] + coeff[2] * rgb[:, 2]
    max_rgb = np.max(rgb, axis=1)
    opponent = max_rgb[:, None] - rgb
    opponent_y = coeff[0] * opponent[:, 0] + coeff[1] * opponent[:, 1] + coeff[2] * opponent[:, 2]
    max_opponent = np.max(opponent, axis=1)
    y_compensate_negative = max_opponent - opponent_y + input_y
    offset = np.maximum(-np.min(rgb, axis=1), 0.0)
    rgb_offset = rgb + offset[:, None]
    max_offset = np.max(rgb_offset, axis=1)
    opponent_offset = max_offset[:, None] - rgb_offset
    max_inverse = np.max(opponent_offset, axis=1)
    y_inverse = coeff[0] * opponent_offset[:, 0] + coeff[1] * opponent_offset[:, 1] + coeff[2] * opponent_offset[:, 2]
    y_new = coeff[0] * rgb_offset[:, 0] + coeff[1] * rgb_offset[:, 1] + coeff[2] * rgb_offset[:, 2]
    y_new = max_inverse - y_inverse + y_new
    ratio = np.ones_like(y_new)
    mask = (y_new > y_compensate_negative) & (y_new > EPS)
    ratio[mask] = y_compensate_negative[mask] / y_new[mask]
    return rgb_offset * ratio[:, None]


def apply_agx_core(rgb_rec2020: Any, plan: ToneCompressionPlan) -> Any:
    """AgX in Rec.2020 working space: inset -> log2 -> sigmoid curve -> outset -> gamma.

    The inset/outset channel crosstalk is what makes this AgX rather than a per-channel
    filmic curve; the darktable-derived sigmoid supplies the curve shape, while the plan's
    black/white EV keep the log2 window anchored on the exposure we set.
    """
    params = agx_curve_params(
        round(plan.black_ev, 3),
        round(plan.white_ev, 3),
        round(plan.contrast, 3),
        round(plan.toe_power, 3),
        round(plan.shoulder_power, 3),
    )
    rgb = agx_compress_into_gamut(rgb_rec2020.astype(np.float32, copy=False))
    inset = apply_rgb_matrix3(rgb, AGX_INSET)
    log_encoded = (np.log2(np.maximum(inset / 0.18, EPS)) - float(params["black_ev"])) / float(params["range_ev"])
    log_encoded = np.clip(log_encoded, 0.0, 1.0)
    curved = agx_apply_curve(log_encoded, params)
    curved = apply_rgb_matrix3(curved, AGX_OUTSET)
    return np.power(np.maximum(curved, 0.0), float(params["gamma"])).astype(np.float32)


def scene_render_to_agx_u8(bundle: RawBundle, plan: ToneCompressionPlan, output_gamut: str = "srgb") -> Any:
    scene = bundle.scene_rec2020_render
    h, w = scene.shape[:2]
    flat_scene = scene.reshape(-1, scene.shape[-1])
    out = np.empty((flat_scene.shape[0], 3), dtype=np.uint8)
    rng = np.random.default_rng(0)
    chunk = 1_000_000

    for start in range(0, flat_scene.shape[0], chunk):
        end = min(start + chunk, flat_scene.shape[0])
        rec = scene_rec2020_to_float(flat_scene[start:end, :3], bundle.scene_scale, bundle.exposure_gain)
        mapped_rec = apply_agx_core(rec, plan)
        output_linear = rec2020_to_output(mapped_rec, output_gamut)
        encoded = srgb_encode(np.clip(output_linear, 0.0, 1.0))
        out[start:end] = dither_quantize_u8(encoded, rng)
    return out.reshape(h, w, 3)


def default_tony_lut_path() -> Path:
    return Path.home() / "dngscan_assets" / "tony_mc_mapface.spi3d"


def load_tony_spi3d(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(
            f"Tony LUT not found: {path}. Download tony_mc_mapface.spi3d from "
            "https://github.com/h3r2tic/tony-mc-mapface/tree/main/OCIO/LUTs or pass --tony-lut."
        )
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


def scene_render_to_tony_u8(
    bundle: RawBundle, plan: ToneCompressionPlan, lut_path: Path, output_gamut: str = "srgb"
) -> Any:
    lut = load_tony_spi3d(lut_path)
    scene = bundle.scene_rec2020_render
    h, w = scene.shape[:2]
    flat_scene = scene.reshape(-1, scene.shape[-1])
    out = np.empty((flat_scene.shape[0], 3), dtype=np.uint8)
    rng = np.random.default_rng(0)
    chunk = 1_000_000
    for start in range(0, flat_scene.shape[0], chunk):
        end = min(start + chunk, flat_scene.shape[0])
        rec = scene_rec2020_to_float(flat_scene[start:end, :3], bundle.scene_scale, bundle.exposure_gain)
        y = luminance_from_rec2020(rec)
        srgb_linear = rec2020_to_srgb(rec)
        srgb_linear = precondition_tonemapper_rgb(srgb_linear, y, plan, for_tony=True)
        mapped_linear = sample_tony_lut(srgb_linear, lut)
        output_linear = srgb_to_output(mapped_linear, output_gamut)
        encoded = srgb_encode(np.clip(output_linear, 0.0, 1.0))
        out[start:end] = dither_quantize_u8(encoded, rng)
    return out.reshape(h, w, 3)


def save_jpeg_array(rgb_u8: Any, out_path: Path, quality: int, output_gamut: str = "srgb") -> bool:
    if mpimg is None:
        raise RuntimeError("matplotlib.image is not available; cannot write JPEG")
    try:
        import PIL  # noqa: F401
    except Exception as exc:
        raise RuntimeError("JPEG 导出需要 Pillow，请先安装 pillow 再重试") from exc
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if rgb_u8.dtype != np.uint8:
        rgb_u8 = np.clip(rgb_u8, 0, 255).astype(np.uint8)
    pil_kwargs: dict[str, Any] = {"quality": int(quality), "subsampling": 0, "optimize": True}
    icc_profile = output_icc_profile_bytes(output_gamut)
    if icc_profile is not None:
        pil_kwargs["icc_profile"] = icc_profile
    mpimg.imsave(
        str(out_path),
        rgb_u8,
        format="jpeg",
        pil_kwargs=pil_kwargs,
    )
    return icc_profile is not None


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


def export_srgb_jpeg(
    path: Path,
    out_path: Path,
    quality: int,
    mode: str,
    bundle: RawBundle,
    analysis: Analysis,
    tony_lut_path: Path | None = None,
    tone_plan: ToneCompressionPlan | None = None,
    output_gamut: str = "srgb",
) -> bool:
    try:
        if mode == "smart":
            plan = tone_plan if tone_plan is not None else plan_for_mode(bundle, analysis, mode, output_gamut)
            rgb = scene_render_to_smart_u8(bundle, analysis, plan, output_gamut)
        elif mode == "agx":
            plan = tone_plan if tone_plan is not None else plan_for_mode(bundle, analysis, mode, output_gamut)
            rgb = scene_render_to_agx_u8(bundle, plan, output_gamut)
        elif mode == "tony":
            plan = tone_plan if tone_plan is not None else plan_for_mode(bundle, analysis, mode, output_gamut)
            lut_path = tony_lut_path if tony_lut_path is not None else default_tony_lut_path()
            rgb = scene_render_to_tony_u8(bundle, plan, lut_path, output_gamut)
        else:
            rgb = scene_render_to_neutral_u8(bundle, output_gamut)
        return save_jpeg_array(rgb, out_path, quality, output_gamut)
    except Exception as exc:
        raise RuntimeError(f"Cannot export 8-bit {output_gamut_label(output_gamut)} JPEG: {exc}") from exc


def load_raw(path: Path, scene_highlight_mode: str = "clip", scene_half_size: bool = False) -> RawBundle:
    if not path.exists():
        raise FileNotFoundError(f"Input file does not exist: {path}")
    if not path.is_file():
        raise FileNotFoundError(f"Input path is not a file: {path}")
    rawpy_highlight_mode(scene_highlight_mode)

    try:
        with rawpy.imread(str(path)) as raw:
            raw_image = np.asarray(raw.raw_image_visible).copy()
            raw_colors = np.asarray(raw.raw_colors_visible).copy()
            if raw_image.size == 0 or raw_colors.size == 0:
                raise RuntimeError("decoded RAW has no visible sensor pixels")
            if raw_image.shape != raw_colors.shape:
                raise RuntimeError("raw_image_visible and raw_colors_visible shapes differ")

            white_level = getattr(raw, "white_level", None)
            if white_level is None:
                white_level = int(np.max(raw_image))
            else:
                white_level = int(white_level)

            xyz_render = render_to_xyz(raw)
            if xyz_render.ndim != 3 or xyz_render.shape[2] < 3:
                raise RuntimeError("XYZ render did not produce a 3-channel image")

            scene_rec2020_render = render_to_scene_rec2020(raw, scene_highlight_mode, scene_half_size)
            if scene_rec2020_render.ndim != 3 or scene_rec2020_render.shape[2] < 3:
                raise RuntimeError("scene Rec.2020 render did not produce a 3-channel image")

            if np.issubdtype(xyz_render.dtype, np.integer):
                render_scale = float(np.iinfo(xyz_render.dtype).max)
            else:
                render_scale = 1.0
            if np.issubdtype(scene_rec2020_render.dtype, np.integer):
                scene_scale = float(np.iinfo(scene_rec2020_render.dtype).max)
            else:
                scene_scale = 1.0

            black_attr = getattr(raw, "black_level_per_channel", None)
            wb_attr = getattr(raw, "camera_whitebalance", None)
            white_pc_attr = getattr(raw, "camera_white_level_per_channel", None)
            orientation_flip = int(getattr(getattr(raw, "sizes", object), "flip", 0) or 0)
            black_levels = list(black_attr) if black_attr is not None else []
            camera_wb = list(wb_attr) if wb_attr is not None else []
            camera_white_levels = list(white_pc_attr) if white_pc_attr is not None else []
            color_desc = decode_color_desc(getattr(raw, "color_desc", ""))
            raw_pattern_arr = getattr(raw, "raw_pattern", [])
            raw_pattern = np.asarray(raw_pattern_arr).astype(int).tolist() if np is not None else []
    except FileNotFoundError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Cannot decode RAW file with rawpy/libraw: {exc}") from exc

    return RawBundle(
        path=path,
        raw_image=raw_image,
        raw_colors=raw_colors,
        xyz_render=xyz_render,
        render_scale=render_scale,
        scene_rec2020_render=scene_rec2020_render,
        scene_scale=scene_scale,
        white_level=white_level,
        black_levels=[float(x) for x in black_levels],
        camera_wb=[float(x) for x in camera_wb],
        color_desc=color_desc,
        raw_pattern=raw_pattern,
        camera_white_levels=[float(x) for x in camera_white_levels],
        scene_highlight_mode=scene_highlight_mode,
        orientation_flip=orientation_flip,
    )


def channel_labels(color_desc: str, channel_ids: list[int]) -> dict[int, str]:
    chars = list(color_desc)
    max_id = max(channel_ids) if channel_ids else -1
    while len(chars) <= max_id:
        chars.append("")

    totals: dict[str, int] = {}
    for ch in chars:
        base = ch if ch and ch.isprintable() else "C"
        totals[base] = totals.get(base, 0) + 1

    seen: dict[str, int] = {}
    labels: dict[int, str] = {}
    for idx, ch in enumerate(chars):
        base = ch if ch and ch.isprintable() else "C"
        seen[base] = seen.get(base, 0) + 1
        if totals.get(base, 0) > 1:
            labels[idx] = f"{base}{seen[base]}"
        else:
            labels[idx] = base if base != "C" else f"C{idx}"

    return {cid: labels.get(cid, f"C{cid}") for cid in channel_ids}


def channel_color(label: str) -> str:
    base = label[:1].upper()
    if base == "R":
        return "#d23"
    if base == "G":
        return "#2a8"
    if base == "B":
        return "#36c"
    return "#7f7f7f"


def format_channel_values(
    values: dict[int, Any], labels: dict[int, str], channel_ids: list[int], fmt: str = "{}"
) -> str:
    parts = []
    for cid in channel_ids:
        val = values.get(cid, "")
        parts.append(f"{labels[cid]}={fmt.format(val)}")
    return " ".join(parts)


def format_pct(value: float) -> str:
    if isinstance(value, float) and math.isnan(value):
        return "n/a"
    if value == 0.0:
        return "0"
    if abs(value) < 0.001:
        return f"{value:.6f}"
    if abs(value) < 1.0:
        return f"{value:.4f}"
    return f"{value:.3f}"


def format_stops(value: float) -> str:
    if isinstance(value, float) and math.isnan(value):
        return "n/a"
    return f"{value:.2f}"


def format_snr_dr(values: dict[str, float]) -> str:
    parts = []
    for group in ("R", "G", "B"):
        val = values.get(group, float("nan"))
        if math.isfinite(val):
            parts.append(f"{group}={val:.2f}")
        else:
            parts.append(f"{group}=n/a")
    return " ".join(parts)


def fullwell_note_cn(note: str) -> str:
    mapping = {
        "weak ceiling channels excluded from fullwell": "弱满阱通道已排除",
        "all channels have ceiling pile": "所有通道都有可靠满阱堆积",
        "no strong ceiling pile; fullwell is uncertain": "没有可靠满阱堆积，满阱估计不确定",
        "no ceiling pile; fullwell from metadata white_level": "无满阱堆积，改用元数据 white_level 估计满阱",
    }
    return mapping.get(note, note)


def channel_list(ids: list[int], labels: dict[int, str]) -> str:
    return "/".join(labels[cid] for cid in ids)


def format_wb_values(values: dict[int, float], labels: dict[int, str], channel_ids: list[int]) -> str:
    g_values = [values[cid] for cid in channel_ids if labels[cid].startswith("G") and values[cid] > 0]
    parts = []
    for cid in channel_ids:
        val = values[cid]
        label = labels[cid]
        if label.startswith("G") and val == 0.0 and g_values:
            parts.append(f"{label}=meta0")
        else:
            parts.append(f"{label}={val:.3g}")
    return " ".join(parts)


def padded_channel_values(values: list[float], channel_ids: list[int]) -> dict[int, float]:
    out: dict[int, float] = {}
    for cid in channel_ids:
        out[cid] = float(values[cid]) if cid < len(values) else 0.0
    return out


def detect_ceilings(raw_image: Any, raw_colors: Any, channel_ids: list[int]) -> tuple[dict[int, int], dict[int, int], dict[int, int], dict[int, bool]]:
    ceilings: dict[int, int] = {}
    exact_counts: dict[int, int] = {}
    near_counts: dict[int, int] = {}
    spike_ok: dict[int, bool] = {}
    for cid in channel_ids:
        vals = raw_image[raw_colors == cid]
        if vals.size == 0:
            raise RuntimeError(f"no visible pixels for raw color channel {cid}")
        ceil = int(np.max(vals))
        exact = int(np.count_nonzero(vals == ceil))
        near = int(np.count_nonzero(vals >= max(ceil - 2, 0)))
        min_pile = max(CEILING_MIN_PILE_PIXELS, int(math.ceil(vals.size * CEILING_MIN_PILE_FRACTION)))
        ceilings[cid] = ceil
        exact_counts[cid] = exact
        near_counts[cid] = near
        spike_ok[cid] = exact >= min_pile or near >= min_pile
    return ceilings, exact_counts, near_counts, spike_ok


def channel_value_map(raw_colors: Any, values: dict[int, Any], default: float, dtype: Any) -> Any:
    max_color = int(np.max(raw_colors)) if raw_colors.size else -1
    levels = np.full(max_color + 1, default, dtype=dtype)
    for cid, value in values.items():
        cid_i = int(cid)
        if 0 <= cid_i <= max_color:
            levels[cid_i] = value
    return levels[raw_colors]


def channel_threshold_map(raw_colors: Any, thresholds: dict[int, int]) -> Any:
    default = int(min(thresholds.values())) if thresholds else 0
    return channel_value_map(raw_colors, thresholds, default, np.int32)


def channel_fullwell_map(raw_colors: Any, fullwell_by_channel: dict[int, int]) -> Any:
    default = float(min(fullwell_by_channel.values())) if fullwell_by_channel else 1.0
    return channel_value_map(raw_colors, fullwell_by_channel, default, np.float32)


def compute_clip_pct_by_thresholds(
    raw_image: Any, raw_colors: Any, channel_ids: list[int], thresholds: dict[int, int]
) -> dict[int, float]:
    out: dict[int, float] = {}
    for cid in channel_ids:
        vals = raw_image[raw_colors == cid]
        threshold = int(thresholds.get(cid, 0))
        out[cid] = float(np.mean(vals >= threshold) * 100.0) if vals.size else 0.0
    return out


def compute_cell_metrics(
    raw_image: Any, raw_colors: Any, thresholds: dict[int, int]
) -> tuple[float, float, dict[int, float], dict[int, float]]:
    h, w = raw_image.shape
    h2 = (h // 2) * 2
    w2 = (w // 2) * 2
    if h2 == 0 or w2 == 0:
        return 0.0, 0.0, {k: 0.0 for k in range(1, 5)}, {k: 0.0 for k in range(1, 5)}

    threshold_map = channel_threshold_map(raw_colors[:h2, :w2], thresholds)
    clipped = raw_image[:h2, :w2] >= threshold_map
    per_cell = clipped.reshape(h2 // 2, 2, w2 // 2, 2).sum(axis=(1, 3))
    total = int(per_cell.size)
    clipped_cells = per_cell >= 1
    clipped_count = int(np.count_nonzero(clipped_cells))
    union_pct = clipped_count / total * 100.0 if total else 0.0

    k_all: dict[int, float] = {}
    k_clipped: dict[int, float] = {}
    for k in range(1, 5):
        count = int(np.count_nonzero(per_cell == k))
        k_all[k] = count / total * 100.0 if total else 0.0
        k_clipped[k] = count / clipped_count * 100.0 if clipped_count else 0.0

    ge2 = int(np.count_nonzero(per_cell >= 2))
    ge2_of_clipped = ge2 / clipped_count * 100.0 if clipped_count else 0.0
    return union_pct, ge2_of_clipped, k_clipped, k_all


def nan_cell_metrics() -> tuple[float, float, dict[int, float], dict[int, float]]:
    nan = float("nan")
    return nan, nan, {k: nan for k in range(1, 5)}, {k: nan for k in range(1, 5)}


def is_2x2_cfa(raw_pattern: list[list[int]]) -> bool:
    try:
        pattern = np.asarray(raw_pattern)
    except Exception:
        return False
    return pattern.shape == (2, 2)


def channel_saturation_levels(
    channel_ids: list[int], camera_white_levels: list[float], white_level: int
) -> dict[int, int]:
    """Per-channel saturation from metadata: camera_white_level_per_channel when the DNG
    provides it, else the global white_level. Zeros (libraw left them unset) fall back too."""
    out: dict[int, int] = {}
    for cid in channel_ids:
        level = int(camera_white_levels[cid]) if cid < len(camera_white_levels) else 0
        out[cid] = level if level > 0 else int(white_level)
    return out


def resolve_fullwell(
    channel_ids: list[int], ceilings: dict[int, int], spike_ok: dict[int, bool], sat: dict[int, int]
) -> tuple[int, list[int], str, dict[int, int]]:
    """Prefer the measured saturation pile when the scene actually clips; otherwise fall back
    to the metadata white level so an unclipped frame's brightest pixel is not mistaken for the
    full well (which would deflate clip %, usable DR, and the tone plan)."""
    strong = [cid for cid in channel_ids if spike_ok.get(cid, False)]
    channel_fullwell = {
        cid: int(ceilings[cid]) if cid in strong else int(sat[cid])
        for cid in channel_ids
    }
    if strong:
        weak = [cid for cid in channel_ids if cid not in strong]
        fullwell = int(min(ceilings[cid] for cid in strong))
        note = "weak ceiling channels excluded from fullwell" if weak else "all channels have ceiling pile"
        return fullwell, strong, note, channel_fullwell
    fullwell = int(min(sat[cid] for cid in channel_ids))
    return fullwell, channel_ids, "no ceiling pile; fullwell from metadata white_level", channel_fullwell


def channel_clip_thresholds(channel_ids: list[int], fullwell_by_channel: dict[int, int], margin: int) -> dict[int, int]:
    return {cid: int(max(fullwell_by_channel[cid] - margin, 0)) for cid in channel_ids}


def luminance_from_xyz_render(xyz_render: Any, render_scale: float) -> Any:
    y = xyz_render[..., 1].astype(np.float32, copy=False)
    y = y / np.float32(render_scale)
    y = np.nan_to_num(y, nan=0.0, posinf=1.0, neginf=0.0)
    return np.clip(y, 0.0, None)


def compute_ev_metrics(y: Any) -> tuple[Any, float, float, float, float, float, float, float, float, float]:
    ev = np.log2(np.clip(y, EPS, None)).astype(np.float32, copy=False)
    ev_report = np.maximum(ev, EV_REPORT_FLOOR)
    raw_p1 = float(np.percentile(ev, 1))
    p1, p50, p99, p999 = [float(x) for x in np.percentile(ev_report, [1, 50, 99, 99.9])]
    floor_hit_pct = float(np.mean(ev <= EV_REPORT_FLOOR) * 100.0)
    return ev, raw_p1, p1, p50, p99, p999, p999 - p1, floor_hit_pct, p50 - GRAY_EV


def estimate_noise_floor(y: Any, rows: int = 32, cols: int = 48) -> float:
    h, w = y.shape
    rows = min(rows, h)
    cols = min(cols, w)
    if rows <= 0 or cols <= 0:
        return 0.0

    y_edges = np.linspace(0, h, rows + 1, dtype=int)
    x_edges = np.linspace(0, w, cols + 1, dtype=int)
    means: list[float] = []
    stds: list[float] = []
    for r in range(rows):
        y0, y1 = int(y_edges[r]), int(y_edges[r + 1])
        if y1 <= y0:
            continue
        for c in range(cols):
            x0, x1 = int(x_edges[c]), int(x_edges[c + 1])
            if x1 <= x0:
                continue
            tile = y[y0:y1, x0:x1]
            if tile.size:
                means.append(float(np.mean(tile, dtype=np.float64)))
                stds.append(float(np.std(tile, dtype=np.float64)))

    if not means:
        return 0.0
    means_arr = np.asarray(means)
    stds_arr = np.asarray(stds)
    count = max(1, int(math.ceil(len(means) * 0.10)))
    darkest = np.argsort(means_arr)[:count]
    return float(np.median(stds_arr[darkest]))


def black_map(raw_colors: Any, black_levels: list[float]) -> Any:
    max_color = int(np.max(raw_colors)) if raw_colors.size else -1
    levels = np.zeros(max_color + 1, dtype=np.float32)
    for cid in range(max_color + 1):
        levels[cid] = float(black_levels[cid]) if cid < len(black_levels) else 0.0
    return levels[raw_colors]


def normalized_raw_signal(
    raw_image: Any, raw_colors: Any, black_levels: list[float], fullwell_by_channel: dict[int, int]
) -> Any:
    bmap = black_map(raw_colors, black_levels)
    fmap = channel_fullwell_map(raw_colors, fullwell_by_channel)
    denom = np.maximum(fmap - bmap, np.float32(1.0))
    signal = raw_image.astype(np.float32, copy=False) - bmap
    signal = np.clip(signal, 0.0, None) / denom
    return np.nan_to_num(signal, nan=0.0, posinf=1.0, neginf=0.0)


def estimate_raw_noise_floor(bundle: RawBundle, fullwell_by_channel: dict[int, int]) -> float:
    signal = normalized_raw_signal(bundle.raw_image, bundle.raw_colors, bundle.black_levels, fullwell_by_channel)
    return estimate_noise_floor(signal)


def cfa_positions_for_channel(bundle: RawBundle, cid: int) -> list[tuple[int, int]]:
    try:
        pattern = np.asarray(bundle.raw_pattern)
    except Exception:
        pattern = np.asarray([])
    if pattern.ndim != 2 or pattern.size == 0:
        return []

    ph, pw = pattern.shape
    visible_pattern = np.asarray(bundle.raw_colors[:ph, :pw])
    positions = np.argwhere(visible_pattern == cid)
    if positions.size == 0:
        positions = np.argwhere(pattern == cid)
    return [(int(y), int(x)) for y, x in positions]


def tile_signal_noise_from_plane(plane: Any, black: float, tile_size: int = SNR_TILE) -> tuple[Any, Any]:
    h, w = plane.shape
    h2 = (h // tile_size) * tile_size
    w2 = (w // tile_size) * tile_size
    if h2 <= 0 or w2 <= 0:
        return np.asarray([], dtype=np.float32), np.asarray([], dtype=np.float32)
    tiles = plane[:h2, :w2].astype(np.float32, copy=False).reshape(
        h2 // tile_size, tile_size, w2 // tile_size, tile_size
    )
    means = tiles.mean(axis=(1, 3), dtype=np.float64).reshape(-1).astype(np.float32)
    stds = tiles.std(axis=(1, 3), dtype=np.float64).reshape(-1).astype(np.float32)
    signal = np.maximum(means - np.float32(black), 0.0)
    return signal, np.maximum(stds, 0.0)


def group_tile_signal_noise(
    bundle: RawBundle, fullwell_by_channel: dict[int, int], ids: list[int]
) -> tuple[Any, Any, Any]:
    signals: list[Any] = []
    noises: list[Any] = []
    denoms: list[Any] = []
    fallback_fullwell = max(fullwell_by_channel.values()) if fullwell_by_channel else 1
    for cid in ids:
        black = float(bundle.black_levels[cid]) if cid < len(bundle.black_levels) else 0.0
        fullwell_f = float(fullwell_by_channel.get(cid, fallback_fullwell))
        denom = max(fullwell_f - black, 1.0)
        for yoff, xoff in cfa_positions_for_channel(bundle, cid):
            pattern = np.asarray(bundle.raw_pattern)
            ph, pw = pattern.shape
            plane = bundle.raw_image[yoff::ph, xoff::pw]
            sig, noise = tile_signal_noise_from_plane(plane, black)
            if sig.size:
                signals.append(sig)
                noises.append(noise)
                denoms.append(np.full(sig.shape, denom, dtype=np.float32))
    if not signals:
        return (
            np.asarray([], dtype=np.float32),
            np.asarray([], dtype=np.float32),
            np.asarray([], dtype=np.float32),
        )
    return np.concatenate(signals), np.concatenate(noises), np.concatenate(denoms)


def interpolate_zero_db_stop(stops: Any, snr_db: Any) -> float:
    valid = np.isfinite(stops) & np.isfinite(snr_db) & (stops <= SNR_BRIGHT_UNRELIABLE_STOP)
    x = stops[valid]
    y = snr_db[valid]
    if x.size < 2:
        return float("nan")
    order = np.argsort(x)
    x = x[order]
    y = y[order]
    if np.all(y > 0):
        return float(x[0])
    if np.all(y < 0):
        return float("nan")
    for i in range(len(x) - 1):
        y0 = float(y[i])
        y1 = float(y[i + 1])
        if y0 == 0.0:
            return float(x[i])
        if (y0 < 0.0 <= y1) or (y0 > 0.0 >= y1):
            x0 = float(x[i])
            x1 = float(x[i + 1])
            if y1 == y0:
                return x0
            return x0 + (0.0 - y0) * (x1 - x0) / (y1 - y0)
    return float("nan")


def compute_snr_curves(
    bundle: RawBundle, channel_ids: list[int], labels: dict[int, str], fullwell_by_channel: dict[int, int]
) -> tuple[dict[str, dict[str, Any]], dict[str, float], dict[str, float]]:
    curves: dict[str, dict[str, Any]] = {}
    snr1_dr: dict[str, float] = {}
    snr1_stop: dict[str, float] = {}
    groups = rgb_channel_groups(channel_ids, labels)
    bins = np.linspace(EV_REPORT_FLOOR, 0.0, 85)
    centers = (bins[:-1] + bins[1:]) * 0.5

    for group_name, ids in groups:
        sig, noise, denom = group_tile_signal_noise(bundle, fullwell_by_channel, ids)
        if sig.size == 0:
            snr_db = np.full(centers.shape, np.nan, dtype=np.float32)
            counts = np.zeros(centers.shape, dtype=np.int32)
        else:
            valid = (sig > 0) & (noise > 0) & (denom > 0)
            stops = np.log2(np.clip(sig[valid] / denom[valid], 2.0 ** EV_REPORT_FLOOR, None))
            sig_valid = sig[valid]
            noise_valid = noise[valid]
            snr_db = np.full(centers.shape, np.nan, dtype=np.float32)
            counts = np.zeros(centers.shape, dtype=np.int32)
            for i in range(len(centers)):
                in_bin = (stops >= bins[i]) & (stops < bins[i + 1])
                n = int(np.count_nonzero(in_bin))
                counts[i] = n
                if n < 8:
                    continue
                noise_est = float(np.percentile(noise_valid[in_bin], SNR_LOW_PERCENTILE))
                signal_med = float(np.median(sig_valid[in_bin]))
                if noise_est <= 0.0 or signal_med <= 0.0:
                    continue
                snr_db[i] = np.float32(20.0 * math.log10(signal_med / max(noise_est, 1e-9)))
        zero_stop = interpolate_zero_db_stop(centers, snr_db)
        snr1_stop[group_name] = zero_stop
        snr1_dr[group_name] = -zero_stop if math.isfinite(zero_stop) else float("nan")
        curves[group_name] = {
            "stops": centers.copy(),
            "snr_db": snr_db,
            "count": counts,
            "ids": ids,
        }
    return curves, snr1_dr, snr1_stop


def compute_gamut_metrics(xyz_render: Any, render_scale: float, y: Any) -> tuple[dict[str, float], float]:
    flat_y = y.reshape(-1)
    median_y = float(np.median(flat_y))
    bright_flat = flat_y > median_y
    if not np.any(bright_flat):
        bright_flat = (flat_y >= median_y) & (flat_y > EPS)

    bright_total = int(np.count_nonzero(bright_flat))
    total_pixels = int(flat_y.size)
    if bright_total == 0:
        return {name: 0.0 for name in XYZ_TO_RGB.keys()}, 0.0

    counts = {name: 0 for name in XYZ_TO_RGB.keys()}
    flat_xyz = xyz_render.reshape(-1, xyz_render.shape[-1])
    inv_scale = np.float32(1.0 / render_scale)
    chunk = 1_000_000

    for start in range(0, total_pixels, chunk):
        end = min(start + chunk, total_pixels)
        mask = bright_flat[start:end]
        if not np.any(mask):
            continue
        xyz = flat_xyz[start:end, :3][mask].astype(np.float32, copy=False) * inv_scale
        xyz = np.nan_to_num(xyz, nan=0.0, posinf=1.0, neginf=0.0)
        x = xyz[:, 0]
        y_chan = xyz[:, 1]
        z = xyz[:, 2]
        for name, matrix in XYZ_TO_RGB.items():
            rgb = np.empty((xyz.shape[0], 3), dtype=np.float32)
            rgb[:, 0] = matrix[0, 0] * x + matrix[0, 1] * y_chan + matrix[0, 2] * z
            rgb[:, 1] = matrix[1, 0] * x + matrix[1, 1] * y_chan + matrix[1, 2] * z
            rgb[:, 2] = matrix[2, 0] * x + matrix[2, 1] * y_chan + matrix[2, 2] * z
            rgb = np.nan_to_num(rgb, nan=0.0, posinf=0.0, neginf=0.0)
            denom = np.max(rgb, axis=1)
            valid = denom > EPS
            if not np.any(valid):
                continue
            norm = rgb[valid] / denom[valid, None]
            counts[name] += int(np.count_nonzero(np.any(norm < -GAMUT_EPS, axis=1)))

    pct = {name: counts[name] / bright_total * 100.0 for name in XYZ_TO_RGB.keys()}
    bright_pct = bright_total / total_pixels * 100.0 if total_pixels else 0.0
    return pct, bright_pct


def estimate_container_bits(white_level: int, raw_image: Any) -> int:
    if white_level > 0:
        return int(math.ceil(math.log2(white_level + 1)))
    if np.issubdtype(raw_image.dtype, np.integer):
        return int(np.iinfo(raw_image.dtype).bits)
    return 0


def analyze(bundle: RawBundle, margin: int) -> tuple[Analysis, Any, Any]:
    raw_image = bundle.raw_image
    raw_colors = bundle.raw_colors
    channel_ids = [int(x) for x in sorted(np.unique(raw_colors).tolist())]
    labels = channel_labels(bundle.color_desc, channel_ids)

    ceilings, exact_counts, near_counts, spike_ok = detect_ceilings(raw_image, raw_colors, channel_ids)
    sat = channel_saturation_levels(channel_ids, bundle.camera_white_levels, bundle.white_level)
    fullwell, fullwell_ids, fullwell_note, channel_fullwell = resolve_fullwell(
        channel_ids, ceilings, spike_ok, sat
    )
    threshold = int(max(fullwell - margin, 0))
    channel_thresholds = channel_clip_thresholds(channel_ids, channel_fullwell, margin)
    clip_pct = compute_clip_pct_by_thresholds(raw_image, raw_colors, channel_ids, channel_thresholds)
    cell_supported = is_2x2_cfa(bundle.raw_pattern)
    if cell_supported:
        cell_union, cell_ge2, cell_k_clipped, cell_k_all = compute_cell_metrics(
            raw_image, raw_colors, channel_thresholds
        )
    else:
        cell_union, cell_ge2, cell_k_clipped, cell_k_all = nan_cell_metrics()

    y = luminance_from_xyz_render(bundle.xyz_render, bundle.render_scale)
    ev, raw_p1, p1, p50, p99, p999, dr, floor_hit_pct, vs_gray = compute_ev_metrics(y)
    nf = estimate_raw_noise_floor(bundle, channel_fullwell)
    usable_dr = math.log2(1.0 / max(nf, NOISE_DR_EPS))
    snr_curves, snr1_dr, snr1_stop = compute_snr_curves(bundle, channel_ids, labels, channel_fullwell)
    gamut_pct, bright_pct = compute_gamut_metrics(bundle.xyz_render, bundle.render_scale, y)

    survivor_id = min(channel_ids, key=lambda cid: clip_pct.get(cid, float("inf")))
    analysis = Analysis(
        channel_ids=channel_ids,
        labels=labels,
        ceilings=ceilings,
        ceil_spike_counts=exact_counts,
        ceil_near_counts=near_counts,
        ceil_spike_ok=spike_ok,
        fullwell_channel_ids=fullwell_ids,
        fullwell_note=fullwell_note,
        saturation_levels=sat,
        channel_fullwell=channel_fullwell,
        channel_thresholds=channel_thresholds,
        fullwell=fullwell,
        threshold=threshold,
        clip_pct=clip_pct,
        cfa_cell_supported=cell_supported,
        cell_union_pct=cell_union,
        cell_ge2_of_clipped_pct=cell_ge2,
        cell_k_of_clipped_pct=cell_k_clipped,
        cell_k_of_all_pct=cell_k_all,
        ev_p1=p1,
        ev_raw_p1=raw_p1,
        ev_median=p50,
        ev_p99=p99,
        ev_p999=p999,
        ev_dr_p1_p999=dr,
        ev_floor_hit_pct=floor_hit_pct,
        median_vs_gray_ev=vs_gray,
        median_y=float(np.median(y)),
        noise_floor=nf,
        usable_dr_ev=usable_dr,
        snr_curves=snr_curves,
        snr1_dr=snr1_dr,
        snr1_stop=snr1_stop,
        gamut_out_pct=gamut_pct,
        bright_pixel_pct=bright_pct,
        survivor_channel=labels[survivor_id],
        container_bits_est=estimate_container_bits(bundle.white_level, raw_image),
    )
    return analysis, y, ev


def downsample_mean(arr: Any, max_dim: int = 900) -> Any:
    h, w = arr.shape
    step = max(1, int(math.ceil(max(h, w) / max_dim)))
    if step <= 1:
        return arr
    h2 = (h // step) * step
    w2 = (w // step) * step
    if h2 <= 0 or w2 <= 0:
        return arr[::step, ::step]
    return arr[:h2, :w2].reshape(h2 // step, step, w2 // step, step).mean(axis=(1, 3))


def downsample_any(mask: Any, max_dim: int = 900) -> Any:
    h, w = mask.shape
    step = max(1, int(math.ceil(max(h, w) / max_dim)))
    if step <= 1:
        return mask
    h2 = (h // step) * step
    w2 = (w // step) * step
    if h2 <= 0 or w2 <= 0:
        return mask[::step, ::step]
    return mask[:h2, :w2].reshape(h2 // step, step, w2 // step, step).any(axis=(1, 3))


def exposure_zone_map(y: Any, nf: float) -> Any:
    y_ds = downsample_mean(y)
    ev_ds = np.log2(np.clip(y_ds, EPS, None))
    noise_ev = math.log2(max(nf, EPS))
    near_noise_cut = max(noise_ev + 1.0, -12.0)

    zones = np.zeros(y_ds.shape, dtype=np.uint8)
    zones[ev_ds > near_noise_cut] = 1
    zones[ev_ds > -5.0] = 2
    zones[ev_ds > -2.0] = 3
    zones[(ev_ds >= -0.05) | (y_ds >= 0.98)] = 4
    return zones


def clipped_rgb_map(bundle: RawBundle, analysis: Analysis) -> Any:
    raw_clip = bundle.raw_image >= channel_threshold_map(bundle.raw_colors, analysis.channel_thresholds)
    groups = {"R": [], "G": [], "B": []}
    for cid in analysis.channel_ids:
        base = analysis.labels[cid][:1].upper()
        if base in groups:
            groups[base].append(cid)

    channels = []
    for base in ("R", "G", "B"):
        ids = groups[base]
        if ids:
            color_match = np.isin(bundle.raw_colors, ids)
            mask = raw_clip & color_match
            channels.append(downsample_any(mask))
        else:
            channels.append(np.zeros_like(downsample_any(raw_clip), dtype=bool))
    return np.dstack(channels).astype(np.float32)


def raw_histogram(vals: Any, xmax: int) -> tuple[Any, Any]:
    if xmax <= 262_144:
        clipped = vals[(vals >= 0) & (vals <= xmax)]
        counts = np.bincount(clipped.astype(np.int64), minlength=xmax + 1)
        x = np.arange(xmax + 1)
        return x, counts
    counts, edges = np.histogram(vals, bins=4096, range=(0, xmax))
    x = (edges[:-1] + edges[1:]) * 0.5
    return x, counts


def smooth_counts(counts: Any, window: int = 9) -> Any:
    if window <= 1 or counts.size < 3:
        return counts.astype(np.float64, copy=False)
    window = min(window, int(counts.size))
    if window % 2 == 0:
        window -= 1
    if window <= 1:
        return counts.astype(np.float64, copy=False)
    kernel = np.ones(window, dtype=np.float64) / float(window)
    return np.convolve(counts.astype(np.float64, copy=False), kernel, mode="same")


def raw_histogram_trend(vals: Any, xmax: int, bins: int = 1024) -> tuple[Any, Any]:
    bins = max(64, min(int(bins), max(int(xmax), 64)))
    counts, edges = np.histogram(vals, bins=bins, range=(0, xmax))
    centers = (edges[:-1] + edges[1:]) * 0.5
    pct = smooth_counts(counts, window=11) / max(int(vals.size), 1) * 100.0
    return centers, pct


def gaussian_kernel1d(sigma: float = 1.2, radius: int | None = None) -> Any:
    if radius is None:
        radius = max(1, int(math.ceil(sigma * 3.0)))
    x = np.arange(-radius, radius + 1, dtype=np.float64)
    kernel = np.exp(-(x * x) / (2.0 * sigma * sigma))
    return kernel / np.sum(kernel)


def gaussian_smooth(counts: Any, sigma: float = 1.2) -> Any:
    if counts.size < 3:
        return counts.astype(np.float64, copy=False)
    kernel = gaussian_kernel1d(sigma)
    return np.convolve(counts.astype(np.float64, copy=False), kernel, mode="same")


def quantile_from_histogram(counts: Any, edges: Any, q: float) -> float:
    total = float(np.sum(counts))
    if total <= 0:
        return float("nan")
    target = total * float(q)
    cumulative = np.cumsum(counts)
    index = int(np.searchsorted(cumulative, target, side="left"))
    index = max(0, min(index, len(edges) - 2))
    return float((edges[index] + edges[index + 1]) * 0.5)


def rgb_ev_histograms_from_xyz(
    xyz_render: Any, render_scale: float, ev_floor: float, ev_high: float, bins: int = 160
) -> tuple[Any, dict[str, Any], dict[str, float], dict[str, float]]:
    edges = np.linspace(ev_floor, ev_high, bins + 1, dtype=np.float32)
    counts = {name: np.zeros(bins, dtype=np.int64) for name in ("R", "G", "B")}
    floor_counts = {name: 0 for name in ("R", "G", "B")}
    matrix = XYZ_TO_RGB["sRGB"]
    flat_xyz = xyz_render.reshape(-1, xyz_render.shape[-1])
    inv_scale = np.float32(1.0 / render_scale)
    total = int(flat_xyz.shape[0])
    chunk = 1_000_000

    for start in range(0, total, chunk):
        end = min(start + chunk, total)
        xyz = flat_xyz[start:end, :3].astype(np.float32, copy=False) * inv_scale
        xyz = np.nan_to_num(xyz, nan=0.0, posinf=1.0, neginf=0.0)
        x = xyz[:, 0]
        y_chan = xyz[:, 1]
        z = xyz[:, 2]
        rgb_values = {
            "R": matrix[0, 0] * x + matrix[0, 1] * y_chan + matrix[0, 2] * z,
            "G": matrix[1, 0] * x + matrix[1, 1] * y_chan + matrix[1, 2] * z,
            "B": matrix[2, 0] * x + matrix[2, 1] * y_chan + matrix[2, 2] * z,
        }
        for name, values in rgb_values.items():
            floor_counts[name] += int(np.count_nonzero(values <= EPS))
            ev_values = np.log2(np.clip(values, EPS, None)).astype(np.float32, copy=False)
            ev_values = np.clip(ev_values, ev_floor, ev_high)
            counts[name] += np.histogram(ev_values, bins=edges)[0]

    medians = {name: quantile_from_histogram(hist, edges, 0.5) for name, hist in counts.items()}
    floor_pct = {name: floor_counts[name] / max(total, 1) * 100.0 for name in counts}
    centers = (edges[:-1] + edges[1:]) * 0.5
    return centers, counts, medians, floor_pct


def rgb_channel_groups(channel_ids: list[int], labels: dict[int, str]) -> list[tuple[str, list[int]]]:
    groups: list[tuple[str, list[int]]] = []
    for base in ("R", "G", "B"):
        ids = [cid for cid in channel_ids if labels[cid].startswith(base)]
        if ids:
            groups.append((base, ids))
    return groups


def stops_for_channel_ids(
    bundle: RawBundle, ids: list[int], fullwell_by_channel: dict[int, int], floor: float
) -> Any:
    masks = [bundle.raw_colors == cid for cid in ids]
    mask = masks[0] if len(masks) == 1 else np.logical_or.reduce(masks)
    raw_vals = bundle.raw_image[mask].astype(np.float32, copy=False)
    color_vals = bundle.raw_colors[mask]
    bmap = black_map(color_vals, bundle.black_levels)
    fmap = channel_fullwell_map(color_vals, fullwell_by_channel)
    denom = np.maximum(fmap - bmap, np.float32(1.0))
    signal = np.maximum(raw_vals - bmap, 0.0)
    min_ratio = np.float32(2.0 ** floor)
    ratio = np.maximum(signal / denom, min_ratio)
    stops = np.log2(ratio).astype(np.float32, copy=False)
    return np.nan_to_num(stops, nan=floor, posinf=0.0, neginf=floor)


def clip_pct_for_channel_ids(bundle: RawBundle, ids: list[int], thresholds: dict[int, int]) -> float:
    masks = [bundle.raw_colors == cid for cid in ids]
    mask = masks[0] if len(masks) == 1 else np.logical_or.reduce(masks)
    vals = bundle.raw_image[mask]
    threshold_vals = channel_threshold_map(bundle.raw_colors[mask], thresholds)
    return float(np.mean(vals >= threshold_vals) * 100.0) if vals.size else 0.0


def normalized_stop_density(stops: Any, x_min: float, x_max: float, bins: int = 180) -> tuple[Any, Any]:
    clipped_stops = np.clip(stops, x_min, x_max)
    counts, edges = np.histogram(clipped_stops, bins=bins, range=(x_min, x_max))
    density = gaussian_smooth(counts, sigma=1.25)
    peak = float(np.max(density)) if density.size else 0.0
    if peak > 0:
        density = density / peak * 100.0
    centers = (edges[:-1] + edges[1:]) * 0.5
    return centers, density


def threshold_stop_for_channel_ids(
    bundle: RawBundle,
    ids: list[int],
    thresholds: dict[int, int],
    fullwell_by_channel: dict[int, int],
    floor: float,
) -> float:
    stops = []
    fallback_fullwell = max(fullwell_by_channel.values()) if fullwell_by_channel else 1
    for cid in ids:
        black = float(bundle.black_levels[cid]) if cid < len(bundle.black_levels) else 0.0
        denom = max(float(fullwell_by_channel.get(cid, fallback_fullwell)) - black, 1.0)
        threshold = float(thresholds.get(cid, 0))
        ratio = max((threshold - black) / denom, 2.0 ** floor)
        stops.append(math.log2(ratio))
    return float(min(stops)) if stops else 0.0


def plot_raw_stop_multiples(fig: Any, ax_slot: Any, bundle: RawBundle, analysis: Analysis) -> None:
    groups = rgb_channel_groups(analysis.channel_ids, analysis.labels)
    if not groups:
        ax_slot.set_axis_off()
        ax_slot.text(0.5, 0.5, "No RGB channels", ha="center", va="center", transform=ax_slot.transAxes)
        return

    raw_spec = ax_slot.get_subplotspec()
    fig.delaxes(ax_slot)
    raw_gs = raw_spec.subgridspec(len(groups), 1, hspace=0.08)
    raw_axes = [fig.add_subplot(raw_gs[i, 0]) for i in range(len(groups))]

    x_min = EV_REPORT_FLOOR
    x_max = 0.25
    color_by_group = {"R": "#d62728", "G": "#2ca02c", "B": "#1f77b4"}

    for index, (group_name, ids) in enumerate(groups):
        ax = raw_axes[index]
        stops = stops_for_channel_ids(bundle, ids, analysis.channel_fullwell, x_min)
        x, density = normalized_stop_density(stops, x_min, x_max)
        median_stop = float(np.median(stops)) if stops.size else float("nan")
        clip_pct = clip_pct_for_channel_ids(bundle, ids, analysis.channel_thresholds)
        thr_stop = threshold_stop_for_channel_ids(
            bundle, ids, analysis.channel_thresholds, analysis.channel_fullwell, x_min
        )
        color = color_by_group.get(group_name, "#555555")

        ax.axvspan(thr_stop, x_max, color="#d62728", alpha=0.10)
        ax.plot(x, density, color=color, lw=1.9)
        ax.fill_between(x, 0, density, color=color, alpha=0.10)
        if not math.isnan(median_stop):
            ax.axvline(median_stop, color=color, ls="--", lw=1.0)
        ax.axvline(thr_stop, color="#d62728", ls=":", lw=1.0)
        ax.set_ylim(0, 105)
        ax.set_xlim(x_min, x_max)
        ax.set_ylabel(group_name, rotation=0, ha="right", va="center", labelpad=18, fontsize=10)
        ax.grid(True, axis="x", alpha=0.18)
        ax.grid(True, axis="y", alpha=0.12)
        ax.text(
            0.98,
            0.75,
            f"clip {format_pct(clip_pct)}%\nmed {median_stop:.2f} EV",
            ha="right",
            va="top",
            transform=ax.transAxes,
            fontsize=8,
            family="monospace",
            bbox={"boxstyle": "round,pad=0.25", "facecolor": "white", "edgecolor": "#cccccc", "alpha": 0.82},
        )
        if index < len(groups) - 1:
            ax.tick_params(axis="x", labelbottom=False)
        else:
            ax.set_xlabel("Stops from clipping: log2((raw - black) / (fullwell - black))")
        if index == 0:
            ax.set_title("Raw Channel Distributions")
    raw_axes[0].text(
        0.01,
        0.88,
        "density peak=100, smoothed for display only",
        transform=raw_axes[0].transAxes,
        fontsize=7.5,
        color="#555555",
        ha="left",
        va="top",
    )


def plot_snr_panel(ax: Any, analysis: Analysis) -> None:
    x_min = EV_REPORT_FLOOR
    x_max = 0.25
    finite_snr1_stops = [v for v in analysis.snr1_stop.values() if math.isfinite(v)]
    usable_floor = max(finite_snr1_stops) if finite_snr1_stops else None

    if usable_floor is not None:
        ax.axvspan(x_min, usable_floor, color="#f5d6d2", alpha=0.34)
        ax.axvspan(usable_floor, SNR_BRIGHT_UNRELIABLE_STOP, color="#f3e5c8", alpha=0.30)
        ax.axvline(usable_floor, color="#b00020", ls=":", lw=1.3, alpha=0.95)
    else:
        ax.axvspan(x_min, SNR_BRIGHT_UNRELIABLE_STOP, color="#f3e5c8", alpha=0.24)
    ax.axvspan(SNR_BRIGHT_UNRELIABLE_STOP, x_max, color="#dddddd", alpha=0.48)
    ax.axvspan(-0.08, x_max, color=channel_color("R"), alpha=0.06)

    for y_ref, label in [
        (0.0, "SNR=1 噪声=信号"),
        (20.0, "SNR=10 可用"),
        (20.0 * math.log10(32.0), "SNR=32 干净"),
    ]:
        ax.axhline(y_ref, color="#666666", ls="--", lw=0.8, alpha=0.7)
        ax.text(x_min + 0.35, y_ref + 0.7, label, fontsize=7.3, color="#555555", va="bottom", ha="left")

    any_curve = False
    for group_name in ("R", "G", "B"):
        curve = analysis.snr_curves.get(group_name)
        if not curve:
            continue
        x = curve["stops"]
        y = curve["snr_db"]
        valid = np.isfinite(x) & np.isfinite(y)
        if not np.any(valid):
            continue
        any_curve = True
        color = channel_color(group_name)
        low_snr = valid & (y < 0.0) & (x <= SNR_BRIGHT_UNRELIABLE_STOP)
        reliable = valid & (y >= 0.0) & (x <= SNR_BRIGHT_UNRELIABLE_STOP)
        unreliable = valid & (x > SNR_BRIGHT_UNRELIABLE_STOP)
        ax.plot(x[low_snr], y[low_snr], color=color, lw=1.4, ls=":", alpha=0.45)
        ax.plot(x[reliable], y[reliable], color=color, lw=2.0)
        ax.plot(x[unreliable], y[unreliable], color=color, lw=1.3, ls="--", alpha=0.45)
        if np.any(reliable):
            last = np.flatnonzero(reliable)[-1]
            ax.text(float(x[last]) + 0.08, float(y[last]), group_name, color=color, fontsize=8, va="center")

    if not any_curve:
        ax.text(0.5, 0.5, "SNR 估计不可用", ha="center", va="center", transform=ax.transAxes)

    finite_values = []
    for curve in analysis.snr_curves.values():
        y = curve["snr_db"]
        finite = y[np.isfinite(y)]
        if finite.size:
            finite_values.append(finite)
    if finite_values:
        all_y = np.concatenate(finite_values)
        y_top = min(70.0, max(35.0, float(np.percentile(all_y, 98)) + 6.0))
    else:
        y_top = 40.0

    ax.set_xlim(x_min, x_max)
    ax.set_ylim(-5.0, y_top)
    ax.set_xlabel("距剪切的档数: log2(signal / fullwell signal)")
    ax.set_ylabel("SNR (dB)")
    ax.set_title("SNR 曲线: 暗部可拉余量")
    ax.grid(True, alpha=0.18)
    if usable_floor is not None:
        ax.text(
            usable_floor - 0.08,
            0.10,
            "SNR=1 可用边界",
            transform=ax.get_xaxis_transform(),
            ha="right",
            va="bottom",
            fontsize=7.3,
            color="#9b0000",
        )
    ax.text(
        x_min + 1.6,
        0.84,
        "噪声主导",
        transform=ax.get_xaxis_transform(),
        ha="left",
        va="top",
        fontsize=7.5,
        color="#9b0000",
    )
    ax.text(
        -6.0,
        0.96,
        "可拉但会发糙",
        transform=ax.get_xaxis_transform(),
        ha="center",
        va="top",
        fontsize=7.5,
        color="#986300",
    )
    ax.text(
        0.02,
        0.96,
        "SNR=1 可用DR\n" + format_snr_dr(analysis.snr1_dr),
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=8,
        bbox={"boxstyle": "round,pad=0.25", "facecolor": "white", "edgecolor": "#cccccc", "alpha": 0.82},
    )
    ax.text(
        SNR_BRIGHT_UNRELIABLE_STOP + 0.08,
        0.94,
        "亮端估计不可靠",
        transform=ax.get_xaxis_transform(),
        fontsize=7.5,
        color="#555555",
        va="top",
    )
    ax.text(
        0.98,
        0.04,
        "单帧估计；灰区不可靠",
        ha="right",
        va="bottom",
        fontsize=7.5,
        color="#555555",
        transform=ax.transAxes,
    )


def plot_rgb_ev_panel(ax: Any, bundle: RawBundle, analysis: Analysis, ev: Any) -> None:
    ev_high = 1.0
    x, counts, medians, floor_pct = rgb_ev_histograms_from_xyz(
        bundle.xyz_render, bundle.render_scale, EV_REPORT_FLOOR, ev_high, bins=160
    )
    total = max(int(bundle.xyz_render.shape[0] * bundle.xyz_render.shape[1]), 1)
    colors = {"R": channel_color("R"), "G": channel_color("G"), "B": channel_color("B")}

    grey_counts, grey_edges = np.histogram(
        np.clip(ev.reshape(-1), EV_REPORT_FLOOR, ev_high), bins=160, range=(EV_REPORT_FLOOR, ev_high)
    )
    grey_x = (grey_edges[:-1] + grey_edges[1:]) * 0.5
    grey_y = gaussian_smooth(grey_counts, sigma=1.0) / total * 100.0
    ax.fill_between(grey_x, 0, grey_y, color="#d7d7d7", alpha=1.0, linewidth=0, label="Y 整体亮度", zorder=1)
    ax.plot(grey_x, grey_y, color="#b0b0b0", lw=0.8, alpha=1.0, zorder=2)

    for name in ("R", "G", "B"):
        y = gaussian_smooth(counts[name], sigma=1.0) / total * 100.0
        label = f"{name} 中位 {medians[name]:.2f} EV"
        ax.plot(x, y, color=colors[name], lw=2.2, alpha=0.98, label=label, zorder=4)
        if math.isfinite(medians[name]):
            ax.axvline(medians[name], color=colors[name], ls="-", lw=0.9, alpha=0.55, zorder=5)

    ax.axvline(GRAY_EV, color="#777777", ls="--", lw=1.0, label="18% 灰", zorder=5)
    ax.axvline(0.0, color="#333333", ls=":", lw=1.0, label="渲染白点", zorder=5)
    ax.set_xlim(EV_REPORT_FLOOR, ev_high)
    ax.set_xlabel("相对线性 sRGB 白点的 EV")
    ax.set_ylabel("每档像素占比 (%)")
    ax.set_title("RGB 曝光分布 + Y 亮度背景")
    ax.legend(fontsize=7.5, loc="upper right", framealpha=0.78)
    ax.grid(True, alpha=0.2)
    floor_note = (
        f"Y p1->p99.9 {analysis.ev_dr_p1_p999:.2f} 档，左端压底 {analysis.ev_floor_hit_pct:.2f}%\n"
        + "通道左端压底: "
        + " ".join(f"{name}={floor_pct[name]:.2f}%" for name in ("R", "G", "B"))
    )
    ax.text(
        0.02,
        0.04,
        floor_note,
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=7.5,
        color="#555555",
    )


def line_style_for_label(label: str) -> str:
    if label.endswith("2"):
        return "--"
    return "-"


def darktable_guidance_lines(bundle: RawBundle, analysis: Analysis) -> list[str]:
    lines = ["Darktable 修图建议:"]
    max_clip = max(analysis.clip_pct.values()) if analysis.clip_pct else 0.0
    if analysis.ev_p999 > -0.10 or max_clip > 0.05:
        lines.append("曝光: 避免全局加曝光；高光已贴近白点，优先局部提暗部。")
    elif analysis.ev_p999 < -0.70 and max_clip < 0.01:
        lines.append(f"曝光: 仍有约 {abs(analysis.ev_p999):.1f} EV 高光余量，可少量全局加曝光。")
    else:
        lines.append("曝光: 高光余量有限；全局曝光先小步调整，再看剪切图。")

    if analysis.cfa_cell_supported and math.isfinite(analysis.cell_union_pct):
        if analysis.cell_union_pct <= 0.01:
            lines.append("高光: RAW 剪切很少，高光重建风险低。")
        elif analysis.cell_ge2_of_clipped_pct >= 50.0:
            lines.append(
                f"高光: {format_pct(analysis.cell_union_pct)}% CFA cell 剪切，且多通道占比高；细节修复有限。"
            )
        else:
            lines.append(
                f"高光: {format_pct(analysis.cell_union_pct)}% CFA cell 剪切，多为单通道；可尝试高光重建。"
            )
    else:
        lines.append("高光: 非 2x2 CFA，剪切结构无法按 Bayer cell 判断。")

    finite_dr = [v for v in analysis.snr1_dr.values() if math.isfinite(v)]
    if finite_dr:
        limiting_dr = min(finite_dr)
        lines.append(f"暗部: 三通道共同可用边界约 {limiting_dr:.2f} 档；更暗处主要是在放大噪声。")
        if limiting_dr < 8.7 or analysis.ev_floor_hit_pct > 1.0:
            lines.append("降噪: 深阴影建议先用配置文件降噪 denoise(profiled)，再控制暗部拉升。")
        else:
            lines.append("降噪: 暗部余量尚可，局部拉阴影时仍需观察色噪。")
    else:
        lines.append("暗部: SNR=1 边界不可用，暗部拉升需以目视噪声为准。")

    srgb_risk = analysis.gamut_out_pct.get("sRGB", 0.0)
    if srgb_risk >= 5.0:
        lines.append(f"色彩: sRGB 高亮越界 {srgb_risk:.2f}%；导出前降低高光色度/饱和度。")
    elif srgb_risk >= 1.0:
        lines.append(f"色彩: sRGB 高亮越界 {srgb_risk:.2f}%；鲜艳高光需留意断层。")
    else:
        lines.append(f"色彩: sRGB 越界 {srgb_risk:.2f}%，常规导出风险较低。")

    wb = padded_channel_values(bundle.camera_wb, analysis.channel_ids)
    boosted = [(analysis.labels[cid], wb[cid]) for cid in analysis.channel_ids if wb[cid] > 1.8]
    if boosted:
        label, gain = max(boosted, key=lambda item: item[1])
        lines.append(f"白平衡: {label} 增益 {gain:.2g} 较高，提亮后该通道噪声/剪切更显眼。")
    return lines


def summary_lines(bundle: RawBundle, analysis: Analysis) -> list[str]:
    black = padded_channel_values(bundle.black_levels, analysis.channel_ids)
    wb = padded_channel_values(bundle.camera_wb, analysis.channel_ids)
    spike_flags = {
        cid: f"{'可靠' if analysis.ceil_spike_ok[cid] else '弱'}({analysis.ceil_spike_counts[cid]})"
        for cid in analysis.channel_ids
    }
    clip_parts = " ".join(
        f"{analysis.labels[cid]}={format_pct(analysis.clip_pct[cid])}" for cid in analysis.channel_ids
    )
    if analysis.cfa_cell_supported:
        cell_line = (
            f"2x2 剪切 cell: {format_pct(analysis.cell_union_pct)}%  "
            f"剪切 cell 中 >=2通道: {format_pct(analysis.cell_ge2_of_clipped_pct)}%"
        )
        cell_mix = "2x2 剪切通道数分布: " + " ".join(
            f"{k}={format_pct(analysis.cell_k_of_clipped_pct[k])}%" for k in range(1, 5)
        )
    else:
        cell_line = "2x2 剪切 cell: n/a (非 2x2 CFA)"
        cell_mix = "2x2 剪切通道数分布: n/a"
    return darktable_guidance_lines(bundle, analysis) + [
        "",
        "关键 RAW 指标:",
        f"文件: {bundle.path.name}",
        f"可见传感器: {bundle.raw_image.shape[1]} x {bundle.raw_image.shape[0]}",
        f"方向标记: flip={bundle.orientation_flip}  JPEG 导出: 按相机方向自动转正",
        f"white_level 标签: {bundle.white_level}  容器位深估计: {analysis.container_bits_est}",
        "黑电平 DN: " + format_channel_values(black, analysis.labels, analysis.channel_ids, "{:.1f}"),
        "相机白平衡: " + format_wb_values(wb, analysis.labels, analysis.channel_ids),
        "元数据白电平 DN: "
        + format_channel_values(analysis.saturation_levels, analysis.labels, analysis.channel_ids, "{}"),
        "观测 ceiling DN: " + format_channel_values(analysis.ceilings, analysis.labels, analysis.channel_ids, "{}"),
        "满阱堆积: " + format_channel_values(spike_flags, analysis.labels, analysis.channel_ids, "{}"),
        "采用满阱 DN: " + format_channel_values(analysis.channel_fullwell, analysis.labels, analysis.channel_ids, "{}"),
        "剪切阈值 DN: " + format_channel_values(analysis.channel_thresholds, analysis.labels, analysis.channel_ids, "{}"),
        f"保守满阱摘要={analysis.fullwell} 来自 {channel_list(analysis.fullwell_channel_ids, analysis.labels)}",
        "满阱说明: " + fullwell_note_cn(analysis.fullwell_note),
        "剪切 %: " + clip_parts,
        cell_line,
        cell_mix,
        f"EV p1/中位/p99/p99.9 下限 {EV_REPORT_FLOOR:.0f}: {analysis.ev_p1:.2f} / {analysis.ev_median:.2f} / "
        f"{analysis.ev_p99:.2f} / {analysis.ev_p999:.2f}",
        f"画面 DR p1->p99.9: {analysis.ev_dr_p1_p999:.2f} 档  左端压底: {analysis.ev_floor_hit_pct:.2f}% 原始p1={analysis.ev_raw_p1:.2f}",
        f"中位亮度相对 18% 灰: {analysis.median_vs_gray_ev:+.2f} EV",
        f"RAW 噪声底: {analysis.noise_floor:.6g}  可用 DR 上限: {analysis.usable_dr_ev:.2f} 档",
        "SNR=1 可用 DR: " + format_snr_dr(analysis.snr1_dr),
        "高亮色域越界 %: "
        + " ".join(f"{name}={analysis.gamut_out_pct[name]:.3f}" for name in ("sRGB", "P3", "Rec2020")),
        f"高亮采样比例: {analysis.bright_pixel_pct:.2f}% 像素",
        f"最不易剪切通道: {analysis.survivor_channel}",
        "注: SNR/噪声为单帧估计，不是光子转移测量。",
    ]


def print_report(
    bundle: RawBundle,
    analysis: Analysis,
    out_path: Path | None,
    csv_path: Path | None,
    jpeg_path: Path | None,
    jpeg_quality: int,
    jpeg_mode: str,
    jpeg_icc_embedded: bool,
    jpeg_ev: float = 0.0,
    tone_plan: ToneCompressionPlan | None = None,
    output_gamut: str = "srgb",
) -> None:
    for line in summary_lines(bundle, analysis):
        print(line)
    if out_path is not None:
        print(f"PNG 图像: {out_path}")
    if csv_path is not None:
        print(f"CSV 指标: {csv_path}")
    if jpeg_path is not None:
        print(f"JPEG 图像: {jpeg_path}")
        print(
            f"JPEG 设置: scene-linear Rec.2020 起点；8-bit {output_gamut_label(output_gamut)}（TPDF 抖动）；"
            "相机白平衡；无自动增亮；"
            f"曝光锚定增益={bundle.exposure_gain:.3f}（EV 补偿={jpeg_ev:+.2f}，固定常数非自适应）；"
            f"模式={jpeg_mode}；高光处理={highlight_mode_cn(bundle.scene_highlight_mode)}；"
            f"质量={jpeg_quality}；4:4:4 色度采样；"
            f"ICC={'已嵌入' if jpeg_icc_embedded else '未嵌入'}"
        )
        print(f"JPEG 策略: {jpeg_policy_cn(jpeg_mode, output_gamut)}")
        plan_line = jpeg_tone_plan_cn(bundle, analysis, jpeg_mode, tone_plan, output_gamut)
        if plan_line:
            print(f"JPEG 自动计划: {plan_line}")


def jpeg_policy_cn(mode: str, output_gamut: str = "srgb") -> str:
    label = output_gamut_label(output_gamut)
    if mode == "neutral":
        return f"neutral: scene-linear Rec.2020 缓冲；相机白平衡；无自动增亮；高光处理按导出选项；不做 tone mapping，转 {label} 时裁切；4:4:4 色度采样"
    if mode == "smart":
        return f"smart: scene-linear 转 linear {label}；相机白平衡；无自动增亮；高光处理按导出选项；同空间亮度锚定；基于色域/剪切/高光/色度分析驱动 knee，做 C1 光滑高光肩与色度收敛，亮度轴裁回不歪色相；4:4:4 色度采样"
    if mode == "agx":
        return f"agx: scene-linear Rec.2020 工作空间；相机白平衡；无自动增亮；高光处理按导出选项；分析全图 Y 自动设定 AgX 黑白相对曝光与曲线；Rec.2020 inset→log2→sigmoid→outset 通道串扰，最后转 {label}；4:4:4 色度采样"
    if mode == "tony":
        return f"tony: scene-linear Rec.2020 缓冲转 linear sRGB stimulus；相机白平衡；无自动增亮；高光处理按导出选项；LUT 前做亮度锚定高光刺激量与色度压缩，再采样 Tony McMapface 3D LUT，最后色彩管理到 {label}；4:4:4 色度采样"
    return ""


def jpeg_tone_plan_cn(
    bundle: RawBundle,
    analysis: Analysis,
    mode: str,
    tone_plan: ToneCompressionPlan | None = None,
    output_gamut: str = "srgb",
) -> str:
    if mode == "smart":
        plan = tone_plan if tone_plan is not None else plan_for_mode(bundle, analysis, mode, output_gamut)
        strength = smart_mapping_strength(analysis, plan)
        return (
            f"smart 强度={strength:.2f}；scene Y p1/p50/p99.9={plan.luma_p1:.4f}/{plan.luma_p50:.4f}/{plan.luma_p999:.4f}；"
            f"{plan.target_gamut} 负通道={plan.negative_rgb_pct:.2f}%，超 1={plan.over_rgb_pct:.2f}%；色度压缩参考={plan.chroma_strength:.2f}"
        )
    if mode == "agx":
        plan = tone_plan if tone_plan is not None else plan_for_mode(bundle, analysis, mode, output_gamut)
        return (
            f"AgX 输入范围 black={plan.black_ev:.2f}EV / white=+{plan.white_ev:.2f}EV，"
            f"DR={plan.dynamic_range_ev:.2f}档；Y p1/p50/p99.9={plan.luma_p1:.4f}/{plan.luma_p50:.4f}/{plan.luma_p999:.4f}；"
            f"曲线 contrast={plan.contrast:.2f}, toe={plan.toe_power:.2f}, shoulder={plan.shoulder_power:.2f}；"
            f"色度压缩={plan.chroma_strength:.2f}，{plan.target_gamut} 负通道={plan.negative_rgb_pct:.2f}%"
        )
    if mode == "tony":
        plan = tone_plan if tone_plan is not None else plan_for_mode(bundle, analysis, mode, output_gamut)
        return (
            f"Tony 输入范围 black={plan.black_ev:.2f}EV / white=+{plan.white_ev:.2f}EV；"
            f"Y p1/p50/p99.9={plan.luma_p1:.4f}/{plan.luma_p50:.4f}/{plan.luma_p999:.4f}；"
            f"高光输入增益={plan.tony_hdr_gain:.2f}；色度压缩={plan.chroma_strength:.2f}，"
            f"sRGB 负通道={plan.negative_rgb_pct:.2f}%，超 1={plan.over_rgb_pct:.2f}%"
        )
    return ""


def csv_row(
    bundle: RawBundle,
    analysis: Analysis,
    out_path: Path | None,
    jpeg_path: Path | None = None,
    jpeg_quality: int | None = None,
    jpeg_mode: str = "",
    jpeg_icc_embedded: bool = False,
    jpeg_ev: float = 0.0,
    tone_plan: ToneCompressionPlan | None = None,
    output_gamut: str = "srgb",
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "file": str(bundle.path),
        "filename": bundle.path.name,
        "width": int(bundle.raw_image.shape[1]),
        "height": int(bundle.raw_image.shape[0]),
        "orientation_flip": int(bundle.orientation_flip),
        "white_level": int(bundle.white_level),
        "container_bits_est": int(analysis.container_bits_est),
        "fullwell_reference": int(analysis.fullwell),
        "fullwell_min_channel_ceil": int(analysis.fullwell),
        "fullwell_channels": channel_list(analysis.fullwell_channel_ids, analysis.labels),
        "fullwell_note": analysis.fullwell_note,
        "threshold_reference": int(analysis.threshold),
        "unified_threshold_thr": int(analysis.threshold),
        "cfa_cell_supported": analysis.cfa_cell_supported,
        "cell_clip_union_pct": analysis.cell_union_pct,
        "cell_clip_ge2_of_clipped_pct": analysis.cell_ge2_of_clipped_pct,
        "ev_raw_p1": analysis.ev_raw_p1,
        "ev_p1": analysis.ev_p1,
        "ev_median": analysis.ev_median,
        "ev_p99": analysis.ev_p99,
        "ev_p99_9": analysis.ev_p999,
        "frame_dr_p1_to_p99_9_stops": analysis.ev_dr_p1_p999,
        "ev_report_floor": EV_REPORT_FLOOR,
        "ev_floor_hit_pct": analysis.ev_floor_hit_pct,
        "median_vs_18pct_gray_ev": analysis.median_vs_gray_ev,
        "raw_noise_floor_single_frame": analysis.noise_floor,
        "usable_dr_noise_limited_upper_bound_stops": analysis.usable_dr_ev,
        "snr1_dr_R": analysis.snr1_dr.get("R", float("nan")),
        "snr1_dr_G": analysis.snr1_dr.get("G", float("nan")),
        "snr1_dr_B": analysis.snr1_dr.get("B", float("nan")),
        "snr1_stop_R": analysis.snr1_stop.get("R", float("nan")),
        "snr1_stop_G": analysis.snr1_stop.get("G", float("nan")),
        "snr1_stop_B": analysis.snr1_stop.get("B", float("nan")),
        "gamut_out_srgb_bright_pct": analysis.gamut_out_pct["sRGB"],
        "gamut_out_p3_bright_pct": analysis.gamut_out_pct["P3"],
        "gamut_out_rec2020_bright_pct": analysis.gamut_out_pct["Rec2020"],
        "bright_pixel_pct": analysis.bright_pixel_pct,
        "survivor_channel": analysis.survivor_channel,
        "png": str(out_path) if out_path is not None else "",
        "jpeg": str(jpeg_path) if jpeg_path is not None else "",
        "jpeg_mode": jpeg_mode if jpeg_path is not None else "",
        "jpeg_output_gamut": output_gamut if jpeg_path is not None else "",
        "jpeg_output_gamut_label": output_gamut_label(output_gamut) if jpeg_path is not None else "",
        "jpeg_highlight_mode": bundle.scene_highlight_mode if jpeg_path is not None else "",
        "jpeg_highlight_mode_cn": highlight_mode_cn(bundle.scene_highlight_mode) if jpeg_path is not None else "",
        "jpeg_quality": int(jpeg_quality) if jpeg_quality is not None else "",
        "jpeg_ev": jpeg_ev if jpeg_path is not None else "",
        "jpeg_exposure_gain": bundle.exposure_gain if jpeg_path is not None else "",
        "jpeg_icc_embedded": jpeg_icc_embedded if jpeg_path is not None else "",
        "jpeg_srgb_icc_embedded": jpeg_icc_embedded if jpeg_path is not None and output_gamut == "srgb" else "",
        "jpeg_policy_cn": jpeg_policy_cn(jpeg_mode, output_gamut) if jpeg_path is not None else "",
        "jpeg_tone_plan_cn": jpeg_tone_plan_cn(bundle, analysis, jpeg_mode, tone_plan, output_gamut) if jpeg_path is not None else "",
        "note": "SNR/噪声为单帧估计，不是光子转移测量；位深不等于可用动态范围。",
        "darktable_guidance_cn": " | ".join(darktable_guidance_lines(bundle, analysis)[1:]),
        "fullwell_note_cn": fullwell_note_cn(analysis.fullwell_note),
    }

    black = padded_channel_values(bundle.black_levels, analysis.channel_ids)
    wb = padded_channel_values(bundle.camera_wb, analysis.channel_ids)
    for cid in analysis.channel_ids:
        label = analysis.labels[cid]
        row[f"black_{label}"] = black[cid]
        row[f"camera_wb_{label}"] = wb[cid]
        row[f"metadata_white_{label}"] = analysis.saturation_levels[cid]
        row[f"ceil_{label}"] = analysis.ceilings[cid]
        row[f"fullwell_{label}"] = analysis.channel_fullwell[cid]
        row[f"clip_threshold_{label}"] = analysis.channel_thresholds[cid]
        row[f"ceil_spike_exact_count_{label}"] = analysis.ceil_spike_counts[cid]
        row[f"ceil_spike_near_count_{label}"] = analysis.ceil_near_counts[cid]
        row[f"ceil_spike_ok_{label}"] = analysis.ceil_spike_ok[cid]
        row[f"clip_pct_{label}"] = analysis.clip_pct[cid]
    for k in range(1, 5):
        row[f"cell_clip_{k}_of_clipped_pct"] = analysis.cell_k_of_clipped_pct[k]
        row[f"cell_clip_{k}_of_all_pct"] = analysis.cell_k_of_all_pct[k]
    return row


def write_csv(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(row.keys()))
        writer.writeheader()
        writer.writerow(row)


def plot_dashboard(bundle: RawBundle, analysis: Analysis, y: Any, ev: Any, out_path: Path) -> None:
    configure_plot_fonts()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fig, axes = plt.subplots(2, 3, figsize=(18, 9), dpi=120, constrained_layout=True)
    ax_raw, ax_ev, ax_gamut, ax_zone, ax_clip, ax_text = axes.ravel()

    plot_snr_panel(ax_raw, analysis)

    plot_rgb_ev_panel(ax_ev, bundle, analysis, ev)

    gamut_names = ["sRGB", "P3", "Rec2020"]
    gamut_vals = [analysis.gamut_out_pct[name] for name in gamut_names]
    bars = ax_gamut.barh(gamut_names, gamut_vals, color=["#e45756", "#72b7b2", "#54a24b"])
    xmax = max(1.0, max(gamut_vals) * 1.25)
    ax_gamut.set_xlim(0, xmax)
    ax_gamut.set_xlabel("高亮像素色域越界比例 (%)")
    ax_gamut.set_title("色域风险: 导出色彩空间")
    for bar, val in zip(bars, gamut_vals):
        ax_gamut.text(val + xmax * 0.02, bar.get_y() + bar.get_height() / 2, f"{val:.3f}%", va="center", fontsize=9)
    ax_gamut.grid(True, axis="x", alpha=0.2)

    zones = exposure_zone_map(y, analysis.noise_floor)
    cmap = ListedColormap(["#080812", "#15376d", "#238b45", "#f3c04d", "#d7191c"])
    ax_zone.imshow(zones, cmap=cmap, vmin=0, vmax=4, interpolation="nearest")
    ax_zone.set_title("曝光区域: 空间 EV 图")
    ax_zone.set_axis_off()
    handles = [
        Patch(facecolor="#080812", label="接近噪声底"),
        Patch(facecolor="#15376d", label="阴影"),
        Patch(facecolor="#238b45", label="中间调"),
        Patch(facecolor="#f3c04d", label="高光"),
        Patch(facecolor="#d7191c", label="剪切"),
    ]
    ax_zone.legend(handles=handles, fontsize=7, loc="lower right", framealpha=0.75)
    ax_zone.text(
        0.01,
        0.02,
        "伪色: 红色=剪切，不代表红光",
        transform=ax_zone.transAxes,
        fontsize=7,
        color="white",
        ha="left",
        va="bottom",
        bbox={"facecolor": "black", "alpha": 0.35, "edgecolor": "none", "pad": 2},
    )

    clip_rgb = clipped_rgb_map(bundle, analysis)
    ax_clip.imshow(clip_rgb, interpolation="nearest")
    ax_clip.set_title("剪切通道: 高光修复地图")
    ax_clip.set_axis_off()
    clip_handles = [
        Patch(facecolor=channel_color("R"), label="R 剪切"),
        Patch(facecolor=channel_color("G"), label="G 剪切"),
        Patch(facecolor=channel_color("B"), label="B 剪切"),
        Patch(facecolor="#ffffff", edgecolor="#999999", label="RGB 全剪切"),
    ]
    ax_clip.legend(handles=clip_handles, fontsize=7, loc="lower right", framealpha=0.75)

    ax_text.set_axis_off()
    ax_text.set_title("摘要: Darktable 修图提示与关键指标")
    ax_text.text(
        0.0,
        1.0,
        "\n".join(summary_lines(bundle, analysis)),
        va="top",
        ha="left",
        fontsize=6.6,
        transform=ax_text.transAxes,
    )

    fig.suptitle(f"RAW 物理诊断: {bundle.path.name}", fontsize=14)
    fig.savefig(out_path)
    plt.close(fig)


def default_png_path(path: Path) -> Path:
    return path.with_name(f"{path.stem}_scan.png")


def main(argv: list[str]) -> int:
    try:
        args = parse_args(argv)
        if not args.path.exists():
            raise FileNotFoundError(f"Input file does not exist: {args.path}")
        if not args.path.is_file():
            raise FileNotFoundError(f"Input path is not a file: {args.path}")
        require_dependencies()
        scan_requested = bool(args.scan or args.out is not None or (args.jpeg is None and args.csv is None))
        out_path = args.out if args.out is not None else (default_png_path(args.path) if scan_requested else None)

        bundle = load_raw(args.path, args.highlight_mode)
        bundle.exposure_gain = compute_exposure_gain(args.jpeg_mode, args.ev)
        analysis, y, ev = analyze(bundle, args.margin)
        if out_path is not None:
            plot_dashboard(bundle, analysis, y, ev, out_path)

        jpeg_path = args.jpeg
        jpeg_icc_embedded = False
        tone_plan = (
            plan_for_mode(bundle, analysis, args.jpeg_mode, args.output_gamut)
            if jpeg_path is not None and args.jpeg_mode != "neutral"
            else None
        )
        if jpeg_path is not None:
            jpeg_icc_embedded = export_srgb_jpeg(
                args.path,
                jpeg_path,
                args.jpeg_quality,
                args.jpeg_mode,
                bundle,
                analysis,
                args.tony_lut,
                tone_plan,
                args.output_gamut,
            )

        row = csv_row(
            bundle,
            analysis,
            out_path,
            jpeg_path,
            args.jpeg_quality if jpeg_path is not None else None,
            args.jpeg_mode if jpeg_path is not None else "",
            jpeg_icc_embedded,
            args.ev,
            tone_plan,
            args.output_gamut,
        )
        if args.csv is not None:
            write_csv(args.csv, row)
        print_report(
            bundle,
            analysis,
            out_path,
            args.csv,
            jpeg_path,
            args.jpeg_quality,
            args.jpeg_mode if jpeg_path is not None else "",
            jpeg_icc_embedded,
            args.ev,
            tone_plan,
            args.output_gamut,
        )
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
