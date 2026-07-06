# SPDX-License-Identifier: GPL-3.0-or-later
"""Command-line entry point."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ._deps import IMPORT_ERRORS
from . import look as look_engine
from .analysis import analyze
from .color import clamp_float
from .constants import (
    CHROMA_CHOICES, DEFAULT_GAINMAP_SCALE, DEFAULT_HDR_HEADROOM_EV, DEMOSAIC_CHOICES,
    JPEG_OUTPUT_FORMATS, WB_CHOICES,
)
from .export import chroma_to_subsampling, export_jpeg
from .plot import default_png_path, plot_dashboard
from .raw_io import load_raw
from .report import csv_row, print_report, write_csv
from .tone import compute_exposure_gain, plan_for_mode
from .auto_ev import AutoEvResult, compute_auto_ev, is_ev_auto, parse_ev_value, resolve_export_ev

def require_dependencies() -> None:
    if IMPORT_ERRORS:
        joined = "\n  ".join(IMPORT_ERRORS)
        raise RuntimeError(
            "Missing or broken dependency. Install only the required packages "
            "(rawpy, numpy, matplotlib) and rerun.\n  " + joined
        )


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
        help="JPEG 质量 1-100（默认 100）",
    )
    parser.add_argument(
        "--chroma",
        choices=CHROMA_CHOICES,
        default="444",
        help="色度采样: 444=满色度(最高保真、体积最大，默认)；422/420=更小体积（420 最小，投递推荐）",
    )
    parser.add_argument(
        "--output-format",
        choices=JPEG_OUTPUT_FORMATS,
        default="sdr",
        help="JPEG 输出格式: sdr=普通 JPEG；ultrahdr=ISO 21496-1 gain-map HDR JPEG（强制 Display P3 底图）",
    )
    parser.add_argument(
        "--hdr-headroom",
        type=float,
        default=DEFAULT_HDR_HEADROOM_EV,
        help="Ultra HDR gain map 的 HDR headroom（档），默认 +3EV",
    )
    parser.add_argument(
        "--hdr-gainmap-scale",
        type=int,
        choices=(1, 2, 4),
        default=DEFAULT_GAINMAP_SCALE,
        help="gain map 降采样倍率；1=全分辨率，2/4=更小体积，默认 2",
    )
    parser.add_argument(
        "--ev",
        default="0",
        help="手动曝光补偿（档），或 auto=画面中位对齐 18%% 灰（高光保护，不过曝）",
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
        "--look",
        choices=look_engine.LOOK_CHOICES,
        default="none",
        help="AgX 之上的色度 look（实测 ARRI 官方 LUT 的 Oklab 几何场）: classic=Classic 709(K1S1) 几何；reveal=ARRI 709(Reveal) 几何；仅 agx 模式",
    )
    parser.add_argument(
        "--look-strength",
        type=float,
        default=1.0,
        help="look 强度 0-1.5（默认 1.0；0=关闭效果）",
    )
    parser.add_argument(
        "--wb",
        choices=WB_CHOICES,
        default="camera",
        help="白平衡: camera=相机 AsShot（默认）；daylight=固定日光配平（胶片式，整卷一致，AsShot 仅作现场光源证词）",
    )
    parser.add_argument(
        "--demosaic",
        choices=DEMOSAIC_CHOICES,
        default="auto",
        help="去马赛克插值算法（画质，非降噪；本工具不做任何降噪。仅全分辨率导出生效): auto=自动选最佳可用(DHT优先，非Bayer走原生)；其余为手动指定",
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
        help="Tony McMapface .spi3d LUT 路径；默认查找 ./dngscan_assets/tony_mc_mapface.spi3d",
    )
    args = parser.parse_args(argv)
    if args.margin < 0:
        parser.error("--margin must be >= 0")
    if not 1 <= args.jpeg_quality <= 100:
        parser.error("--jpeg-quality must be between 1 and 100")
    if args.hdr_headroom <= 0:
        parser.error("--hdr-headroom must be > 0")
    return args


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

        bundle = load_raw(args.path, args.highlight_mode, demosaic=args.demosaic, wb_mode=args.wb)
        analysis, y, ev = analyze(bundle, args.margin)

        ev_input = parse_ev_value(args.ev)
        auto_ev_result: AutoEvResult | None = None
        jpeg_output_gamut = "p3" if args.output_format == "ultrahdr" else args.output_gamut
        if is_ev_auto(ev_input):
            if args.jpeg is None and not scan_requested:
                raise ValueError("--ev auto 需要同时导出 JPEG（--jpeg）或诊断图（--scan / --out）")
            resolved_ev, auto_ev_result = resolve_export_ev(
                ev_input, bundle, analysis, args.jpeg_mode, jpeg_output_gamut
            )
        else:
            resolved_ev = float(ev_input)

        bundle.exposure_gain = compute_exposure_gain(args.jpeg_mode, resolved_ev)
        if out_path is not None:
            plot_dashboard(bundle, analysis, y, ev, out_path, auto_ev=auto_ev_result)

        jpeg_path = args.jpeg
        jpeg_icc_embedded = False
        jpeg_output_gamut = "p3" if args.output_format == "ultrahdr" else args.output_gamut
        tone_plan = (
            plan_for_mode(bundle, analysis, args.jpeg_mode, jpeg_output_gamut)
            if jpeg_path is not None and args.jpeg_mode != "neutral"
            else None
        )
        if jpeg_path is not None:
            jpeg_icc_embedded = export_jpeg(
                args.path,
                jpeg_path,
                args.jpeg_quality,
                args.jpeg_mode,
                bundle,
                analysis,
                args.tony_lut,
                tone_plan,
                jpeg_output_gamut,
                args.output_format,
                args.hdr_headroom,
                args.hdr_gainmap_scale,
                chroma_to_subsampling(args.chroma),
                args.look,
                clamp_float(args.look_strength, 0.0, 1.5),
            )

        row = csv_row(
            bundle,
            analysis,
            out_path,
            jpeg_path,
            args.jpeg_quality if jpeg_path is not None else None,
            args.jpeg_mode if jpeg_path is not None else "",
            jpeg_icc_embedded,
            resolved_ev,
            tone_plan,
            jpeg_output_gamut,
            auto_ev_result,
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
            resolved_ev,
            tone_plan,
            jpeg_output_gamut,
            auto_ev_result,
        )
        if jpeg_path is not None and args.output_format == "ultrahdr":
            print(f"JPEG HDR: ISO 21496-1 gain-map；headroom=+{args.hdr_headroom:.2f}EV；gain map scale=1/{args.hdr_gainmap_scale}")
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

