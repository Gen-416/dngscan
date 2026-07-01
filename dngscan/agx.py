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

# Reference AgX inset/outset from Troy Sobotka's AgX family, expressed for
# sRGB/Rec.709 primaries. dngscan conjugates this matrix into Rec.2020 so the
# view transform can run in the same wide scene-linear space as the RAW buffer.
REFERENCE_INSET = (
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


def build_inset_outset(srgb_to_rec2020: Any, rec2020_to_srgb: Any) -> tuple[Any, Any]:
    if np is None or srgb_to_rec2020 is None or rec2020_to_srgb is None or REFERENCE_INSET is None:
        return None, None
    inset = (srgb_to_rec2020 @ REFERENCE_INSET @ rec2020_to_srgb).astype(np.float64)
    inset = (inset / inset.sum(axis=1, keepdims=True)).astype(np.float64)
    return inset, np.linalg.inv(inset).astype(np.float64)


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

    toe_transition_x = max(EPS, pivot_x)
    toe_transition_y = pivot_y
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

    shoulder_transition_x = min(1.0 - EPS, pivot_x)
    shoulder_transition_y = pivot_y
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
    # Pure AgX sigmoid: no linear latitude. Toe and shoulder meet at the pivot, so every value
    # is either toe (below pivot) or shoulder (>= pivot); both halves pass through pivot_y, so
    # the split is continuous. (darktable's latitude control is intentionally not used.)
    toe = x < float(params["toe_transition_x"])
    shoulder = ~toe
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


def apply_core(rgb_rec2020: Any, plan: Any, inset_matrix: Any, outset_matrix: Any) -> Any:
    """AgX in Rec.2020 working space: inset -> log2 -> sigmoid curve -> outset -> gamma."""
    params = curve_params(
        round(plan.black_ev, 3),
        round(plan.white_ev, 3),
        round(plan.contrast, 3),
        round(plan.toe_power, 3),
        round(plan.shoulder_power, 3),
    )
    rgb = compress_into_gamut(rgb_rec2020.astype(np.float32, copy=False))
    inset = _apply_matrix3(rgb, inset_matrix)
    log_encoded = (np.log2(np.maximum(inset / 0.18, EPS)) - float(params["black_ev"])) / float(params["range_ev"])
    log_encoded = np.clip(log_encoded, 0.0, 1.0)
    curved = apply_curve(log_encoded, params)
    curved = _apply_matrix3(curved, outset_matrix)
    return np.power(np.maximum(curved, 0.0), float(params["gamma"])).astype(np.float32)
