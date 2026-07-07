# SPDX-License-Identifier: GPL-3.0-or-later
"""Luminance-ratio shoulder core used as an AgX alternative."""
from __future__ import annotations

from typing import Any

from ._deps import np
from . import agx as agx_engine
from .color import EPS, luminance_from_rec2020

REC2020_LUMA = np.asarray([0.2627, 0.6780, 0.0593], dtype=np.float32)


def norm_rec2020(rgb_rec2020: Any, mode: str = "y", power: float = 4.0) -> Any:
    rgb = np.asarray(rgb_rec2020, dtype=np.float32)
    positive = np.maximum(rgb, 0.0)
    if mode == "max":
        return np.max(positive, axis=1)
    if mode == "power":
        p = np.float32(max(1.0, float(power)))
        weighted = (
            REC2020_LUMA[0] * np.power(positive[:, 0], p)
            + REC2020_LUMA[1] * np.power(positive[:, 1], p)
            + REC2020_LUMA[2] * np.power(positive[:, 2], p)
        )
        return np.power(np.maximum(weighted, 0.0), np.float32(1.0) / p)
    return np.maximum(luminance_from_rec2020(rgb), 0.0)


def apply_lum_core(rgb_rec2020: Any, plan: Any) -> Any:
    """Apply the existing AgX sigmoid to a scalar norm and preserve RGB ratios."""
    rgb = np.asarray(rgb_rec2020, dtype=np.float32)
    mode = str(getattr(plan, "lum_norm", "y"))
    norm = norm_rec2020(rgb, mode)
    params = agx_engine.curve_params(
        round(plan.black_ev, 3),
        round(plan.white_ev, 3),
        round(plan.contrast, 3),
        round(plan.toe_power, 3),
        round(plan.shoulder_power, 3),
        round(float(getattr(plan, "latitude_lo_ev", 0.0)), 3),
        round(float(getattr(plan, "latitude_hi_ev", 0.0)), 3),
    )
    log_encoded = (np.log2(np.maximum(norm / np.float32(0.18), EPS)) - float(params["black_ev"])) / float(params["range_ev"])
    log_encoded = np.clip(log_encoded, 0.0, 1.0)
    curved = agx_engine.apply_curve(log_encoded, params)
    mapped_norm = np.power(np.maximum(curved, 0.0), float(params["gamma"]))
    ratio = np.zeros_like(mapped_norm, dtype=np.float32)
    valid = norm > np.float32(EPS)
    ratio[valid] = mapped_norm[valid] / np.maximum(norm[valid], np.float32(EPS))
    return (rgb * ratio[:, None]).astype(np.float32, copy=False)
