# SPDX-License-Identifier: GPL-3.0-or-later
"""RAW-gated display DRT: darktable-style luminance C1 + permission-weighted AgX color path."""
from __future__ import annotations

from typing import Any

from ._deps import np
from . import agx as agx_engine
from . import guidance as guidance_engine
from . import lum as lum_engine
from . import punch as punch_engine
from .color import luminance_from_rec2020
from .models import ColorGeometryPlan, ToneCompressionPlan


def apply_gated_core(
    rgb_rec2020: Any,
    plan: ToneCompressionPlan,
    color_plan: ColorGeometryPlan | None = None,
    clip_masks_rgb: Any | None = None,
    raw_guidance: Any | None = None,
) -> Any:
    """Luma-first C1 shoulder with RAW-gated AgX colour geometry.

    The C1 luminance result is the sole brightness authority. AgX supplies a chromatic
    path-to-white which is re-normalized to the same Rec.2020 Y before blending, so a
    CFA confidence boundary cannot create a brightness seam.
    """
    rgb = np.asarray(rgb_rec2020, dtype=np.float32)
    lum_mapped = lum_engine.apply_lum_core(rgb, plan)

    inset, outset = agx_engine.formation_matrices(plan)
    agx_mapped = agx_engine.apply_core(rgb, plan, inset, outset)
    agx_mapped = punch_engine.apply_punch_rec2020(agx_mapped, float(getattr(plan, "punch_strength", 0.0)))
    target_y = luminance_from_rec2020(lum_mapped)
    agx_y = luminance_from_rec2020(agx_mapped)
    ratio = np.zeros_like(target_y, dtype=np.float32)
    valid = (target_y > np.float32(1e-7)) & (agx_y > np.float32(1e-7))
    ratio[valid] = target_y[valid] / agx_y[valid]
    agx_chroma = agx_mapped * ratio[:, None]
    agx_chroma[~valid] = lum_mapped[~valid]

    scene_ev = guidance_engine.scene_ev_from_rec2020(rgb)
    pressure = float(color_plan.output_gamut_pressure_pct) if color_plan is not None else 0.0
    midtone_protect = float(getattr(color_plan, "gated_midtone_protect", 0.92)) if color_plan else 0.92
    ev_lo = float(getattr(color_plan, "color_path_highlight_ev_lo", 0.25)) if color_plan else 0.25
    ev_hi = float(getattr(color_plan, "color_path_highlight_ev_hi", 2.75)) if color_plan else 2.75
    master = float(getattr(color_plan, "color_path_master", 1.0)) if color_plan else 1.0
    noise_floor = float(getattr(color_plan, "gated_noise_ev_floor", -12.0)) if color_plan else -12.0

    w = guidance_engine.color_path_weight(
        clip_masks_rgb,
        scene_ev,
        pressure,
        scene_rgb_rec2020=rgb,
        noise_ev_floor=noise_floor,
        raw_headroom_rgb=getattr(raw_guidance, "headroom", None),
        raw_clip_class=getattr(raw_guidance, "clip_class", None),
        raw_snr_confidence=getattr(raw_guidance, "snr_confidence", None),
        midtone_protect=midtone_protect,
        highlight_ev_lo=ev_lo,
        highlight_ev_hi=ev_hi,
    )
    w = np.clip(w * np.float32(master), 0.0, 1.0)[:, None]
    return (lum_mapped * (np.float32(1.0) - w) + agx_chroma * w).astype(np.float32, copy=False)
