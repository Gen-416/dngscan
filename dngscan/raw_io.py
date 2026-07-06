# SPDX-License-Identifier: GPL-3.0-or-later
"""RAW decode via rawpy and scene-linear render buffers."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ._deps import np, rawpy
from . import metadata as dng_metadata
from .constants import DEMOSAIC_AUTO_PREFERENCE, DEMOSAIC_CHOICES, WB_CHOICES
from .models import RawBundle

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


def wb_postprocess_kwargs(wb_mode: str, daylight_wb: list[float] | None) -> dict[str, Any]:
    """Film-style fixed balance ('daylight', libraw's calibrated daylight multipliers)
    or the as-shot camera balance (default). One dict so every render agrees."""
    if wb_mode == "daylight" and daylight_wb is not None and any(v > 0 for v in daylight_wb[:3]):
        return {"use_camera_wb": False, "user_wb": [float(v) for v in daylight_wb[:4]]}
    if wb_mode not in WB_CHOICES:
        raise ValueError(f"unknown wb mode: {wb_mode}")
    return {"use_camera_wb": True}


def render_to_xyz(
    raw: Any,
    highlight_mode_name: str = "clip",
    demosaic: Any = None,
    half_size: bool = False,
    wb_kwargs: dict[str, Any] | None = None,
) -> Any:
    if not hasattr(rawpy.ColorSpace, "XYZ"):
        raise RuntimeError("rawpy.ColorSpace.XYZ is not available; cannot make device-independent EV/gamut metrics")
    # Render-dependent analysis (luminance, EV, gamut risk) uses the SAME demosaic and
    # highlight mode as the export buffer, so the stats match the image you actually get.
    # user_flip=0 keeps it unrotated and aligned with the raw-domain CFA maps.
    return raw.postprocess(
        output_color=rawpy.ColorSpace.XYZ,
        gamma=(1, 1),
        half_size=half_size,
        demosaic_algorithm=(None if half_size else demosaic),
        no_auto_bright=True,
        highlight_mode=rawpy_highlight_mode(highlight_mode_name),
        output_bps=16,
        user_flip=0,
        **(wb_kwargs or {"use_camera_wb": True}),
    )


def resolve_demosaic_algorithm(raw: Any, requested: str) -> Any:
    """Pick a DemosaicAlgorithm for the full-res export, or None (libraw default).

    Non-Bayer sensors (e.g. X-Trans) keep libraw's native path. 'auto' takes the best
    available Bayer detail algorithm (DHT preferred); an explicit request is honored when
    the build supports it, else it falls back to auto."""
    if rawpy is None:
        return None
    pattern = getattr(raw, "raw_pattern", None)
    is_bayer = pattern is not None and getattr(pattern, "shape", None) == (2, 2)
    if not is_bayer:
        return None

    def supported(name: str) -> Any:
        alg = getattr(rawpy.DemosaicAlgorithm, name.upper(), None)
        if alg is not None and getattr(alg, "isSupported", False):
            return alg
        return None

    if requested and requested != "auto":
        chosen = supported(requested)
        if chosen is not None:
            return chosen
    for name in DEMOSAIC_AUTO_PREFERENCE:
        chosen = supported(name)
        if chosen is not None:
            return chosen
    return None


def render_to_scene_rec2020(
    raw: Any,
    highlight_mode_name: str = "clip",
    half_size: bool = False,
    demosaic: Any = None,
    wb_kwargs: dict[str, Any] | None = None,
) -> Any:
    if not hasattr(rawpy.ColorSpace, "Rec2020"):
        raise RuntimeError("rawpy.ColorSpace.Rec2020 is not available; cannot make scene-linear export buffer")
    return raw.postprocess(
        output_color=rawpy.ColorSpace.Rec2020,
        gamma=(1, 1),
        half_size=half_size,
        demosaic_algorithm=(None if half_size else demosaic),
        no_auto_bright=True,
        highlight_mode=rawpy_highlight_mode(highlight_mode_name),
        output_bps=16,
        user_flip=None,
        **(wb_kwargs or {"use_camera_wb": True}),
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


def load_raw(
    path: Path,
    scene_highlight_mode: str = "clip",
    scene_half_size: bool = False,
    demosaic: str = "auto",
    wb_mode: str = "camera",
) -> RawBundle:
    if not path.exists():
        raise FileNotFoundError(f"Input file does not exist: {path}")
    if not path.is_file():
        raise FileNotFoundError(f"Input path is not a file: {path}")
    rawpy_highlight_mode(scene_highlight_mode)
    shot = dng_metadata.read_dng_shot_info(path)

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

            daylight_attr = getattr(raw, "daylight_whitebalance", None)
            daylight_wb = [float(v) for v in daylight_attr] if daylight_attr is not None else None
            wb_kwargs = wb_postprocess_kwargs(wb_mode, daylight_wb)

            demosaic_alg = resolve_demosaic_algorithm(raw, demosaic)
            xyz_render = render_to_xyz(raw, scene_highlight_mode, demosaic_alg, scene_half_size, wb_kwargs)
            if xyz_render.ndim != 3 or xyz_render.shape[2] < 3:
                raise RuntimeError("XYZ render did not produce a 3-channel image")

            scene_rec2020_render = render_to_scene_rec2020(
                raw, scene_highlight_mode, scene_half_size, demosaic_alg, wb_kwargs
            )
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
        wb_mode=wb_mode,
        daylight_wb=daylight_wb,
        shot_make=shot.make,
        shot_model=shot.model,
        shot_iso=shot.iso,
    )

