# SPDX-License-Identifier: GPL-3.0-or-later
"""AgX view-transform core used by dngscan's JPEG export pipeline."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

try:
    import numpy as np
except Exception:  # pragma: no cover - handled by dngscan.core import checks
    np = None  # type: ignore[assignment]

EPS = 1e-12

# Blender AgX (EaryChow) Rec.2020-native inset/outset, computed at float64 precision by
# running the reference generation expressions from EaryChow/AgX_LUT_Gen
# (AgXBaseRec2020.py + working_space.py via colour-science):
#   inset:  primaries_rotate=[2.13976149, -1.22827335, -3.05174246] degrees,
#           primaries_scale=[0.32965205, 0.28051336, 0.12475368]
#   outset: no rotation, primaries_scale=[0.32317438, 0.28325605, 0.0374326]
# Cross-checked against the matrix printed in the EaryChow/AgX README. The rotation baked
# into the inset is AgX's "flourish" (e.g. red drifts toward orange, countering Abney);
# the outset deliberately does NOT invert it, so AGX_OUTSET_REC2020 != inv(AGX_INSET_REC2020).
AGX_INSET_REC2020 = (
    np.array(  # type: ignore[union-attr]
        [
            [0.8566271562887795, 0.0951212454025350, 0.0482515983086858],
            [0.1373189722835516, 0.7612419870090806, 0.1014390407073675],
            [0.1118982080451796, 0.0767994145625176, 0.8113023773923032],
        ],
        dtype=np.float64,
    )
    if np is not None
    else None
)
AGX_OUTSET_REC2020 = (
    np.array(  # type: ignore[union-attr]
        [
            [1.1271005696301188, -0.1106066385782607, -0.0164939310518590],
            [-0.1413297544213532, 1.1578236854732127, -0.0164939310518590],
            [-0.1413297544213531, -0.1106066385782606, 1.2519363929996135],
        ],
        dtype=np.float64,
    )
    if np is not None
    else None
)

# Fraction of the per-channel hue shift kept after the curve (Blender AgX mix_percent=40:
# lerp 60% of the hue back toward the pre-formation angle so the deliberate primaries
# rotation is not amplified by per-channel "notorious six" skew).
AGX_HUE_KEEP = 0.4


def _clamp_float(value: float, low: float, high: float) -> float:
    return min(high, max(low, float(value)))


def _apply_matrix3(rgb: Any, matrix: Any) -> Any:
    out = np.empty((rgb.shape[0], 3), dtype=np.float32)
    out[:, 0] = matrix[0, 0] * rgb[:, 0] + matrix[0, 1] * rgb[:, 1] + matrix[0, 2] * rgb[:, 2]
    out[:, 1] = matrix[1, 0] * rgb[:, 0] + matrix[1, 1] * rgb[:, 1] + matrix[1, 2] * rgb[:, 2]
    out[:, 2] = matrix[2, 0] * rgb[:, 0] + matrix[2, 1] * rgb[:, 1] + matrix[2, 2] * rgb[:, 2]
    return out


@lru_cache(maxsize=32)
def curve_params(
    black_ev: float = -10.0,
    white_ev: float = 6.5,
    contrast: float = 3.0,
    toe_power: float = 1.5,
    shoulder_power: float = 3.3,
    latitude_lo_ev: float = 0.0,
    latitude_hi_ev: float = 0.0,
) -> dict[str, float | bool]:
    # Derived from darktable's GPLv3 AgX implementation:
    # https://github.com/darktable-org/darktable/blob/master/src/iop/agx.c
    # and its OpenCL kernel:
    # https://github.com/darktable-org/darktable/blob/master/data/kernels/agx.cl
    default_gamma = 2.2
    black_ev = float(black_ev)
    white_ev = float(white_ev)
    range_ev = max(1.0, white_ev - black_ev)
    pivot_x = _clamp_float(-black_ev / range_ev, EPS, 1.0 - EPS)
    pivot_y_linear = 0.18
    pivot_y = pivot_y_linear ** (1.0 / default_gamma)
    target_black = 0.0
    target_white = 1.0
    range_adjusted_slope = contrast * (range_ev / 16.5)
    pivot_y_default = pivot_y
    derivative_current = default_gamma * max(EPS, pivot_y) ** (default_gamma - 1.0)
    derivative_default = default_gamma * max(EPS, pivot_y_default) ** (default_gamma - 1.0)
    slope = range_adjusted_slope / (derivative_current / derivative_default)

    # Latitude: a linear mid segment through the pivot. With zero latitude the curve is
    # Troy's pure sigmoid (toe meets shoulder at mid gray) — which converges channels and
    # washes chroma from mid gray UP. Scene-driven latitude pushes the shoulder start
    # above the subject's colorful range in bright wide-DR scenes. Clamped so the linear
    # run cannot leave the display range.
    lat_lo_x = _clamp_float(max(0.0, latitude_lo_ev) / range_ev, 0.0, pivot_x - EPS)
    lat_hi_x = _clamp_float(max(0.0, latitude_hi_ev) / range_ev, 0.0, 1.0 - pivot_x - EPS)
    if slope > EPS:
        lat_lo_x = min(lat_lo_x, (pivot_y - 0.02) / slope)
        lat_hi_x = min(lat_hi_x, (0.95 - pivot_y) / slope)

    toe_transition_x = max(EPS, pivot_x - lat_lo_x)
    toe_transition_y = max(EPS, pivot_y - slope * lat_lo_x)
    inverse_toe_limit_x = 1.0
    inverse_toe_limit_y = 1.0 - target_black
    inverse_toe_transition_x = 1.0 - toe_transition_x
    inverse_toe_transition_y = 1.0 - toe_transition_y
    toe_scale = -scale(
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

    shoulder_transition_x = min(1.0 - EPS, pivot_x + lat_hi_x)
    shoulder_transition_y = min(1.0 - EPS, pivot_y + slope * lat_hi_x)
    shoulder_scale = scale(1.0, target_white, shoulder_transition_x, shoulder_transition_y, slope, shoulder_power)
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
        "intercept": pivot_y - slope * pivot_x,
        "shoulder_power": shoulder_power,
        "shoulder_transition_x": shoulder_transition_x,
        "shoulder_transition_y": shoulder_transition_y,
        "shoulder_scale": shoulder_scale,
        "need_concave_shoulder": need_concave_shoulder,
        "shoulder_fallback_power": shoulder_fallback_power,
        "shoulder_fallback_coefficient": shoulder_fallback_coefficient,
    }


def scale(limit_x: float, limit_y: float, transition_x: float, transition_y: float, slope: float, power: float) -> float:
    projected_rise = slope * max(EPS, limit_x - transition_x)
    actual_rise = max(EPS, limit_y - transition_y)
    base = max(EPS, actual_rise ** (-power) - projected_rise ** (-power))
    return min(1e9, base ** (-1.0 / power))


def sigmoid(x: Any, power: float) -> Any:
    return x / np.power(1.0 + np.power(x, power), 1.0 / power)


def scaled_sigmoid(x: Any, scale_value: float, slope: float, power: float, transition_x: float, transition_y: float) -> Any:
    return scale_value * sigmoid(slope * (x - transition_x) / scale_value, power) + transition_y


def apply_curve(x: Any, params: dict[str, float | bool]) -> Any:
    x = np.asarray(x, dtype=np.float32)
    out = np.empty_like(x)
    # Toe below, shoulder above, and a linear latitude segment through the pivot between
    # them (empty when latitude is zero — then this degenerates to Troy's pure sigmoid).
    # All three pieces share value and slope at the transitions, so the curve stays C1.
    toe = x < float(params["toe_transition_x"])
    shoulder = x > float(params["shoulder_transition_x"])
    mid = ~(toe | shoulder)
    if np.any(mid):
        out[mid] = float(params["slope"]) * x[mid] + float(params["intercept"])
    if np.any(toe):
        if bool(params["need_convex_toe"]):
            out[toe] = float(params["target_black"]) + np.maximum(
                0.0,
                float(params["toe_fallback_coefficient"]) * np.power(np.maximum(x[toe], 0.0), float(params["toe_fallback_power"])),
            )
        else:
            out[toe] = scaled_sigmoid(
                x[toe],
                float(params["toe_scale"]),
                float(params["slope"]),
                float(params["toe_power"]),
                float(params["toe_transition_x"]),
                float(params["toe_transition_y"]),
            )
    if np.any(shoulder):
        if bool(params["need_concave_shoulder"]):
            out[shoulder] = float(params["target_white"]) - np.maximum(
                0.0,
                float(params["shoulder_fallback_coefficient"])
                * np.power(np.maximum(1.0 - x[shoulder], 0.0), float(params["shoulder_fallback_power"])),
            )
        else:
            out[shoulder] = scaled_sigmoid(
                x[shoulder],
                float(params["shoulder_scale"]),
                float(params["slope"]),
                float(params["shoulder_power"]),
                float(params["shoulder_transition_x"]),
                float(params["shoulder_transition_y"]),
            )
    return np.clip(out, float(params["target_black"]), float(params["target_white"]))


def compress_into_gamut(rgb: Any) -> Any:
    # Rec.2020 luminance weights: this gamut compression runs on Rec.2020 data (pre-inset),
    # so preserving Rec.2020 Y keeps the luminance it protects consistent with the working space.
    coeff = np.asarray([0.2627, 0.6780, 0.0593], dtype=np.float32)
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


def _rgb_to_hsv(rgb: Any) -> Any:
    r, g, b = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    maxc = np.max(rgb, axis=1)
    minc = np.min(rgb, axis=1)
    delta = maxc - minc
    h = np.zeros_like(maxc)
    mask = delta > EPS
    rmask = mask & (maxc == r)
    gmask = mask & (maxc == g) & ~rmask
    bmask = mask & ~rmask & ~gmask
    h[rmask] = ((g[rmask] - b[rmask]) / delta[rmask]) % 6.0
    h[gmask] = (b[gmask] - r[gmask]) / delta[gmask] + 2.0
    h[bmask] = (r[bmask] - g[bmask]) / delta[bmask] + 4.0
    h = (h / 6.0) % 1.0
    s = np.zeros_like(maxc)
    positive = maxc > EPS
    s[positive] = delta[positive] / maxc[positive]
    return np.stack([h, s, maxc], axis=1)


def _hsv_to_rgb(hsv: Any) -> Any:
    h = (hsv[:, 0] % 1.0) * 6.0
    s = np.clip(hsv[:, 1], 0.0, None)
    v = hsv[:, 2]
    i = np.floor(h).astype(np.int32) % 6
    f = h - np.floor(h)
    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))
    out = np.empty((hsv.shape[0], 3), dtype=np.float32)
    for idx, (cr, cg, cb) in enumerate([(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)]):
        m = i == idx
        if np.any(m):
            out[m, 0] = cr[m]
            out[m, 1] = cg[m]
            out[m, 2] = cb[m]
    return out


def _mix_hue(rgb_linear: Any, pre_hue: Any, keep: float) -> Any:
    """Lerp the post-curve hue back toward the pre-formation hue along the shortest arc,
    keeping `keep` of the per-channel shift (Blender AgX's mix_percent hack)."""
    hsv = _rgb_to_hsv(rgb_linear)
    delta = hsv[:, 0] - pre_hue
    delta -= np.rint(delta)
    hsv[:, 0] = (pre_hue + np.float32(keep) * delta) % 1.0
    return _hsv_to_rgb(hsv)


def apply_core(rgb_rec2020: Any, plan: Any, inset_matrix: Any, outset_matrix: Any) -> Any:
    """AgX per Blender/EaryChow reference order, in Rec.2020 working space:

    guard rail -> inset (rotation+attenuation) -> log2 window -> sigmoid ->
    linearize -> hue mix (keep 40% of per-channel shift) -> outset in LINEAR light.

    Deviations from the reference, both deliberate: the log2 window and sigmoid
    parameters come from the scene analysis plan (reference uses fixed [-10,+6.5] and
    fixed contrast), and linearization uses the darktable-derived 2.2 pivot the curve
    was parameterized with (reference encodes 2.4).
    """
    params = curve_params(
        round(plan.black_ev, 3),
        round(plan.white_ev, 3),
        round(plan.contrast, 3),
        round(plan.toe_power, 3),
        round(plan.shoulder_power, 3),
        round(float(getattr(plan, "latitude_lo_ev", 0.0)), 3),
        round(float(getattr(plan, "latitude_hi_ev", 0.0)), 3),
    )
    rgb = compress_into_gamut(rgb_rec2020.astype(np.float32, copy=False))
    inset = _apply_matrix3(rgb, inset_matrix)
    pre_hue = _rgb_to_hsv(np.maximum(inset, 0.0))[:, 0]
    log_encoded = (np.log2(np.maximum(inset / 0.18, EPS)) - float(params["black_ev"])) / float(params["range_ev"])
    log_encoded = np.clip(log_encoded, 0.0, 1.0)
    curved = apply_curve(log_encoded, params)
    linear = np.power(np.maximum(curved, 0.0), float(params["gamma"]))
    linear = _mix_hue(linear, pre_hue, AGX_HUE_KEEP)
    return _apply_matrix3(linear, outset_matrix).astype(np.float32)
