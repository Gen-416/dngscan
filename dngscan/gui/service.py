# SPDX-License-Identifier: GPL-3.0-or-later
"""Preview/export job logic for the local web GUI."""
from __future__ import annotations

import base64
import io
import math
import threading
from dataclasses import dataclass, replace
from pathlib import Path

import dngscan as dg
from dngscan.look import LOOK_CHOICES

from .constants import PROXY_LONG_EDGE, RAW_EXTS


@dataclass
class PreviewEntry:
    bundle: dg.RawBundle
    analysis: dg.Analysis
    proxy_scene: object


PREVIEW_CACHE: dict[tuple[str, int, str], PreviewEntry] = {}
PREVIEW_CACHE_LOCK = threading.Lock()
RENDER_LOCK = threading.Lock()

def downsample_mean(image: object, max_long_edge: int = PROXY_LONG_EDGE) -> object:
    np = dg.np
    if np is None:
        return image
    arr = np.asarray(image)
    h, w = arr.shape[:2]
    long_edge = max(h, w)
    if long_edge <= max_long_edge:
        return arr
    factor = max(1, int(math.ceil(long_edge / max_long_edge)))
    work = arr.astype(np.float32, copy=False)
    row_starts = np.arange(0, h, factor)
    col_starts = np.arange(0, w, factor)
    reduced = np.add.reduceat(work, row_starts, axis=0)
    reduced = np.add.reduceat(reduced, col_starts, axis=1)
    row_counts = np.diff(np.append(row_starts, h)).astype(np.float32)
    col_counts = np.diff(np.append(col_starts, w)).astype(np.float32)
    reduced = reduced / row_counts[:, None, None]
    reduced = reduced / col_counts[None, :, None]
    return reduced.astype(np.float32, copy=False)


def make_preview_b64(path: Path, width: int | None = 1280, icc_profile: bytes | None = None) -> str:
    from PIL import Image

    with Image.open(path) as src:
        if icc_profile is None:
            icc_profile = src.info.get("icc_profile")
        im = src.convert("RGB")
    if width is not None and im.width > width:
        im = im.resize((width, round(im.height * width / im.width)))
    buf = io.BytesIO()
    save_kwargs = {"format": "JPEG", "quality": 85}
    if icc_profile:
        save_kwargs["icc_profile"] = icc_profile
    im.save(buf, **save_kwargs)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def preview_b64_from_u8(rgb_u8: object, icc_profile: bytes | None = None) -> str:
    from PIL import Image

    im = Image.fromarray(rgb_u8, "RGB")
    buf = io.BytesIO()
    save_kwargs = {"format": "JPEG", "quality": 85}
    if icc_profile:
        save_kwargs["icc_profile"] = icc_profile
    im.save(buf, **save_kwargs)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def annotate_preview_rgb_u8(rgb_u8: object, lines: list[str]) -> object:
    from PIL import Image, ImageDraw, ImageFont

    np = dg.np
    if np is None or not lines:
        return rgb_u8
    base = np.asarray(rgb_u8, dtype=np.uint8)
    im = Image.fromarray(base, "RGB")
    overlay = Image.new("RGBA", im.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    w, h = im.size
    pad = max(10, h // 100)
    font_size = max(16, h // 42)
    font = None
    for path in (
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
    ):
        try:
            font = ImageFont.truetype(path, font_size)
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default()
    line_gap = max(4, font_size // 6)
    text_heights = []
    text_widths = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        text_widths.append(bbox[2] - bbox[0])
        text_heights.append(bbox[3] - bbox[1])
    box_w = max(text_widths) + pad * 2
    box_h = sum(text_heights) + line_gap * (len(lines) - 1) + pad * 2
    draw.rectangle((pad, pad, pad + box_w, pad + box_h), fill=(12, 16, 24, 210))
    y_cursor = pad + pad // 2
    for line, th in zip(lines, text_heights):
        draw.text((pad * 2, y_cursor), line, fill=(255, 236, 170, 255), font=font)
        y_cursor += th + line_gap
    composed = Image.alpha_composite(im.convert("RGBA"), overlay)
    return np.asarray(composed.convert("RGB"), dtype=np.uint8)


def auto_ev_payload(result: dg.AutoEvResult | None) -> dict | None:
    if result is None:
        return None
    return {
        "ev": result.ev,
        "ev_boost": result.ev_boost,
        "ev_median_target": result.ev_median_target,
        "highlight_limited": result.highlight_limited,
        "highlight_cap_ev": result.highlight_cap_ev,
        "anchored_median_ev": result.anchored_median_ev,
    }


def preview_metrics_from_u8(rgb_u8: object, gamut: str) -> dict[str, float]:
    np = dg.np
    if np is None:
        return {}
    rgb = np.asarray(rgb_u8, dtype=np.uint8)
    flat_u8 = rgb.reshape(-1, 3)
    max_channel = np.max(flat_u8, axis=1)
    weights = dg.RGB_TO_XYZ[dg.output_gamut_space(gamut)][1].astype(np.float32)
    y_u8 = (
        weights[0] * flat_u8[:, 0].astype(np.float32)
        + weights[1] * flat_u8[:, 1].astype(np.float32)
        + weights[2] * flat_u8[:, 2].astype(np.float32)
    )
    return {
        "luma_p999_pct": float(np.percentile(y_u8, 99.9) / 255.0 * 100.0),
        "near_white_pct": float(np.mean(max_channel >= 250) * 100.0),
        "clipped_channel_pct": float(np.mean(max_channel >= 254) * 100.0),
    }


def output_luminance_metrics(path: Path, gamut: str, ev: float) -> dict[str, float]:
    from PIL import Image

    np = dg.np
    if np is None:
        return {}
    im = Image.open(path).convert("RGB")
    encoded_u8 = np.asarray(im, dtype=np.uint8)
    encoded = encoded_u8.astype(np.float32) / np.float32(255.0)
    flat = encoded.reshape(-1, 3)
    max_channel_u8 = np.max(encoded_u8.reshape(-1, 3), axis=1)
    linear = np.where(flat <= 0.04045, flat / 12.92, np.power((flat + 0.055) / 1.055, 2.4))
    matrix = dg.RGB_TO_XYZ[dg.output_gamut_space(gamut)]
    y = matrix[1, 0] * linear[:, 0] + matrix[1, 1] * linear[:, 1] + matrix[1, 2] * linear[:, 2]
    y = np.clip(np.nan_to_num(y, nan=0.0, posinf=1.0, neginf=0.0), 0.0, 1.0)
    max_channel = np.max(linear, axis=1)
    y_p99, y_p999 = [float(v) for v in np.percentile(y, [99.0, 99.9])]
    max_p999 = float(np.percentile(max_channel, 99.9))
    headroom_luma_ev = math.log2(0.95 / max(y_p999, 1e-9))
    headroom_rgb_ev = math.log2(0.98 / max(max_p999, 1e-9))
    return {
        "median_luma_pct": float(np.median(y) * 100.0),
        "mean_luma_pct": float(np.mean(y) * 100.0),
        "luma_p99_pct": y_p99 * 100.0,
        "luma_p999_pct": y_p999 * 100.0,
        "max_channel_p999_pct": max_p999 * 100.0,
        "near_white_pct": float(np.mean(max_channel_u8 >= 250) * 100.0),
        "clipped_channel_pct": float(np.mean(max_channel_u8 >= 254) * 100.0),
        "headroom_luma_ev": float(headroom_luma_ev),
        "headroom_rgb_ev": float(headroom_rgb_ev),
        "estimated_ev_before_luma_limit": float(ev + headroom_luma_ev),
    }


def output_metrics_from_linear(rgb_linear: object, gamut: str) -> dict[str, float]:
    np = dg.np
    if np is None:
        return {}
    rgb = np.clip(np.nan_to_num(rgb_linear, nan=0.0, posinf=1.0, neginf=0.0), 0.0, 1.0)
    matrix = dg.RGB_TO_XYZ[dg.output_gamut_space(gamut)]
    y = matrix[1, 0] * rgb[:, 0] + matrix[1, 1] * rgb[:, 1] + matrix[1, 2] * rgb[:, 2]
    y = np.clip(np.nan_to_num(y, nan=0.0, posinf=1.0, neginf=0.0), 0.0, 1.0)
    max_channel = np.max(rgb, axis=1)
    y_p999 = float(np.percentile(y, 99.9))
    max_p999 = float(np.percentile(max_channel, 99.9))
    return {
        "luma_p999_pct": y_p999 * 100.0,
        "max_channel_p999_pct": max_p999 * 100.0,
        "near_white_pct": float(np.mean(max_channel >= np.float32(0.956)) * 100.0),
        "clipped_channel_pct": float(np.mean(np.any(rgb >= np.float32(0.999), axis=1)) * 100.0),
    }


def estimate_ev_headroom(
    bundle: dg.RawBundle,
    analysis: dg.Analysis | None,
    mode: str,
    gamut: str,
    current_ev: float,
    max_samples: int = 220_000,
) -> dict[str, float | str]:
    if analysis is None:
        return {}
    safe_ev = dg.max_safe_ev(bundle, analysis, mode, gamut, from_ev=current_ev, max_samples=max_samples)
    return {
        "safe_ev_remaining": max(0.0, float(safe_ev - current_ev)),
        "estimated_safe_ev": float(safe_ev),
        "headroom_limit": "p99.9高光/通道顶白/近白比例阈值",
    }


def list_dir(raw: str) -> dict:
    p = Path(raw).expanduser() if raw else Path.home()
    if not p.is_dir():
        p = Path.home()
    dirs: list[str] = []
    files: list[str] = []
    try:
        for entry in sorted(p.iterdir(), key=lambda x: x.name.lower()):
            try:
                if entry.name.startswith("."):
                    continue
                if entry.is_dir():
                    dirs.append(entry.name)
                elif entry.suffix.lower() in RAW_EXTS:
                    files.append(entry.name)
            except OSError:
                continue
    except PermissionError:
        pass
    return {"cwd": str(p), "parent": str(p.parent), "dirs": dirs, "files": files}


def parse_job_params(params: dict) -> tuple[Path, str, str, str, str, float, float, int, bool, Path | None, bool]:
    inp = Path(str(params["input"])).expanduser()
    if not inp.is_file():
        raise FileNotFoundError(f"文件不存在：{inp}")
    mode = str(params.get("mode", "neutral"))
    if mode not in ("neutral", "smart", "agx", "tony"):
        raise ValueError(f"未知模式：{mode}")
    highlight = str(params.get("highlight", "clip"))
    if highlight not in ("clip", "blend", "reconstruct"):
        raise ValueError(f"未知高光处理：{highlight}")
    gamut = str(params.get("gamut", "srgb"))
    if gamut not in ("srgb", "p3"):
        raise ValueError(f"未知输出色域：{gamut}")
    output_format = str(params.get("format", "sdr"))
    if output_format not in dg.JPEG_OUTPUT_FORMATS:
        raise ValueError(f"未知输出格式：{output_format}")
    if output_format == "ultrahdr":
        gamut = "p3"
    ev = float(params.get("ev", 0.0))
    hdr_headroom = float(params.get("hdrHeadroom", dg.DEFAULT_HDR_HEADROOM_EV))
    if hdr_headroom <= 0:
        raise ValueError("HDR headroom 必须大于 0")
    quality = int(params.get("quality", 100))
    if not 1 <= quality <= 100:
        raise ValueError("质量需在 1-100 之间")
    want_png = bool(params.get("png", False))
    outdir = Path(str(params["outdir"])).expanduser() if params.get("outdir") else None
    ev_auto = bool(params.get("evAuto", False))
    return inp, mode, highlight, gamut, output_format, ev, hdr_headroom, quality, want_png, outdir, ev_auto


def plan_for_bundle(bundle: dg.RawBundle, analysis: dg.Analysis, mode: str, gamut: str) -> dg.ToneCompressionPlan | None:
    return dg.plan_for_mode(bundle, analysis, mode, gamut) if mode != "neutral" else None


def export_preview_jpeg(
    inp: Path,
    mode: str,
    highlight: str,
    gamut: str,
    ev: float,
    quality: int,
    max_width: int = 1400,
    wb: str = "camera",
    look: str = "none",
    look_strength: float = 1.0,
    auto_ev: dg.AutoEvResult | None = None,
) -> dict:
    dg.require_dependencies()
    stat = inp.stat()
    key = (str(inp), int(stat.st_mtime_ns), highlight, wb)
    with PREVIEW_CACHE_LOCK:
        cached = PREVIEW_CACHE.get(key)
    if cached is None:
        bundle = dg.load_raw(inp, highlight, scene_half_size=True, wb_mode=wb)
        analysis, _, _ = dg.analyze(bundle, 4)
        proxy_scene = downsample_mean(bundle.scene_rec2020_render, PROXY_LONG_EDGE)
        cached = PreviewEntry(bundle=bundle, analysis=analysis, proxy_scene=proxy_scene)
        with PREVIEW_CACHE_LOCK:
            PREVIEW_CACHE.clear()
            PREVIEW_CACHE[key] = cached

    proxy_bundle = replace(
        cached.bundle,
        scene_rec2020_render=cached.proxy_scene,
        exposure_gain=dg.compute_exposure_gain(mode, ev),
    )
    with RENDER_LOCK:
        tone_plan = plan_for_bundle(proxy_bundle, cached.analysis, mode, gamut)
        icc_profile = dg.output_icc_profile_bytes(gamut)
        rgb_u8 = dg.render_output_u8(
            proxy_bundle, cached.analysis, mode, gamut, None, tone_plan, look, look_strength
        )
        if auto_ev is not None:
            rgb_u8 = annotate_preview_rgb_u8(rgb_u8, dg.auto_ev_overlay_lines(auto_ev))
        metrics = preview_metrics_from_u8(rgb_u8, gamut)
        preview = preview_b64_from_u8(rgb_u8, icc_profile=icc_profile)
    payload = {
        "ok": True,
        "preview": preview,
        "metrics": metrics,
        "metrics_kind": "preview",
        "gain": proxy_bundle.exposure_gain,
        "ev": ev,
        "highlight": dg.highlight_mode_cn(highlight),
        "gamut": dg.output_gamut_label(gamut),
        "ev_auto": auto_ev_payload(auto_ev),
    }
    return payload


def parse_look(params: dict, mode: str) -> tuple[str, float]:
    look = str(params.get("look", "none"))
    if look not in LOOK_CHOICES:
        raise ValueError(f"未知 look：{look}")
    if look != "none" and mode != "agx":
        raise ValueError("look 目前仅支持 agx 模式")
    strength = float(params.get("lookStrength", 1.0))
    return look, max(0.0, min(1.5, strength))


def run_preview(params: dict) -> dict:
    inp, mode, highlight, gamut, _, ev, _, quality, _, _, ev_auto = parse_job_params(params)
    wb = str(params.get("wb", "camera"))
    if wb not in dg.WB_CHOICES:
        raise ValueError(f"未知白平衡模式：{wb}")
    look, look_strength = parse_look(params, mode)
    auto_ev_result = None
    if ev_auto:
        stat = inp.stat()
        key = (str(inp), int(stat.st_mtime_ns), highlight, wb)
        with PREVIEW_CACHE_LOCK:
            cached = PREVIEW_CACHE.get(key)
        if cached is None:
            bundle = dg.load_raw(inp, highlight, scene_half_size=True, wb_mode=wb)
            analysis, _, _ = dg.analyze(bundle, 4)
            proxy_scene = downsample_mean(bundle.scene_rec2020_render, PROXY_LONG_EDGE)
            cached = PreviewEntry(bundle=bundle, analysis=analysis, proxy_scene=proxy_scene)
            with PREVIEW_CACHE_LOCK:
                PREVIEW_CACHE.clear()
                PREVIEW_CACHE[key] = cached
        auto_ev_result = dg.compute_auto_ev(cached.bundle, cached.analysis, mode, gamut)
        ev = auto_ev_result.ev
    return export_preview_jpeg(
        inp,
        mode,
        highlight,
        gamut,
        ev,
        min(quality, 95),
        wb=wb,
        look=look,
        look_strength=look_strength,
        auto_ev=auto_ev_result,
    )


def run_export(params: dict) -> dict:
    dg.require_dependencies()
    inp, mode, highlight, gamut, output_format, ev, hdr_headroom, quality, want_png, outdir_arg, ev_auto = parse_job_params(
        params
    )
    outdir = outdir_arg if outdir_arg is not None else inp.parent
    outdir.mkdir(parents=True, exist_ok=True)

    demosaic = str(params.get("demosaic", "auto"))
    chroma = str(params.get("chroma", "444"))
    wb = str(params.get("wb", "camera"))
    if wb not in dg.WB_CHOICES:
        raise ValueError(f"未知白平衡模式：{wb}")
    look, look_strength = parse_look(params, mode)
    bundle = dg.load_raw(inp, highlight, demosaic=demosaic, wb_mode=wb)

    analysis = None
    y = ev_img = None
    if mode != "neutral" or want_png or ev_auto:
        analysis, y, ev_img = dg.analyze(bundle, 4)
    auto_ev_result = None
    if ev_auto:
        if analysis is None:
            analysis, y, ev_img = dg.analyze(bundle, 4)
        auto_ev_result = dg.compute_auto_ev(bundle, analysis, mode, gamut)
        ev = auto_ev_result.ev
    bundle.exposure_gain = dg.compute_exposure_gain(mode, ev)
    tone_plan = plan_for_bundle(bundle, analysis, mode, gamut) if analysis is not None else None

    suffix_parts = [mode]
    if highlight != "clip":
        suffix_parts.append(highlight)
    if gamut != "srgb":
        suffix_parts.append(gamut)
    if output_format == "ultrahdr":
        suffix_parts.append("hdr")
    suffix = "_".join(suffix_parts)
    jpg_path = outdir / f"{inp.stem}_{suffix}.jpg"
    with RENDER_LOCK:
        bundle.exposure_gain = dg.compute_exposure_gain(mode, ev)
        icc_profile = dg.output_icc_profile_bytes(gamut)
        dg.export_jpeg(
            inp,
            jpg_path,
            quality,
            mode,
            bundle,
            analysis,
            None,
            tone_plan,
            gamut,
            output_format,
            hdr_headroom,
            dg.DEFAULT_GAINMAP_SCALE,
            dg.chroma_to_subsampling(chroma),
            look,
            look_strength,
        )
        metrics = output_luminance_metrics(jpg_path, gamut, ev)
        metrics.update(estimate_ev_headroom(bundle, analysis, mode, gamut, ev, max_samples=600_000))
        preview = make_preview_b64(jpg_path, icc_profile=icc_profile)
        if auto_ev_result is not None:
            from PIL import Image

            np = dg.np
            im = Image.open(jpg_path).convert("RGB")
            annotated = annotate_preview_rgb_u8(np.asarray(im), dg.auto_ev_overlay_lines(auto_ev_result))
            preview = preview_b64_from_u8(annotated, icc_profile=icc_profile)
        saved = [str(jpg_path)]

        if want_png:
            png_path = outdir / f"{inp.stem}_scan.png"
            dg.plot_dashboard(bundle, analysis, y, ev_img, png_path, auto_ev=auto_ev_result)
            saved.append(str(png_path))

    return {
        "ok": True,
        "saved": saved,
        "preview": preview,
        "metrics": metrics,
        "metrics_kind": "full",
        "gain": bundle.exposure_gain,
        "ev": ev,
        "ev_auto": auto_ev_payload(auto_ev_result),
        "format": "HDR gain-map JPEG" if output_format == "ultrahdr" else "SDR JPEG",
        "hdr_headroom": hdr_headroom if output_format == "ultrahdr" else 0.0,
        "highlight": dg.highlight_mode_cn(highlight),
        "gamut": dg.output_gamut_label(gamut),
    }

