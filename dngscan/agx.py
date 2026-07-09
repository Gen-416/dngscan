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
# rotation is not amplified by per-channel "notorious six" skew). Default; per-plan/look
# overridable via ToneCompressionPlan.hue_keep.
AGX_HUE_KEEP = 0.4

# Internal y-axis encoding the curve was originally parameterized with. Kept as the
# reference for the contrast (derivative) compensation when the adaptive gamma moves
# the pivot toward the diagonal (darktable's "keep the pivot on the diagonal").
DEFAULT_CURVE_GAMMA = 2.2

# Minimum x-run reserved for the toe and shoulder segments. Latitude may never push a
# transition closer than this to the log window edge; previously the shoulder could
# collapse to ~zero length (transition_x clamped to 1-EPS while transition_y was
# computed from the unclamped latitude), leaving whites unreachable except through a
# near-discontinuous fallback.
MIN_SEGMENT_X = 0.06

# AgX primaries presets (darktable-inspired): scalars deriving the effective outset.
#   purity  — mix between identity and the purity-restoring outset (>1 extrapolates);
#   rotation_reversal — mix of the outset toward inv(inset), undoing the inset's
#   deliberate hue rotation (darktable's "master rotation reversal").
AGX_PRIMARIES_PRESETS: dict[str, tuple[float, float]] = {
    "base": (1.0, 0.0),
    "punchy": (1.25, 0.0),
    "smooth": (0.85, 1.0),
}
AGX_PRIMARIES_CHOICES = tuple(AGX_PRIMARIES_PRESETS.keys())


def _clamp_float(value: float, low: float, high: float) -> float:
    return min(high, max(low, float(value)))


def _apply_matrix3(rgb: Any, matrix: Any) -> Any:
    out = np.empty((rgb.shape[0], 3), dtype=np.float32)
    out[:, 0] = matrix[0, 0] * rgb[:, 0] + matrix[0, 1] * rgb[:, 1] + matrix[0, 2] * rgb[:, 2]
    out[:, 1] = matrix[1, 0] * rgb[:, 0] + matrix[1, 1] * rgb[:, 1] + matrix[1, 2] * rgb[:, 2]
    out[:, 2] = matrix[2, 0] * rgb[:, 0] + matrix[2, 1] * rgb[:, 1] + matrix[2, 2] * rgb[:, 2]
    return out


def _build_curve_params(
    black_ev: float,
    white_ev: float,
    contrast: float,
    toe_power: float,
    shoulder_power: float,
    latitude_lo_ev: float,
    latitude_hi_ev: float,
    pivot_x: float,
    pivot_y_linear: float,
    gamma: float,
    target_black_linear: float,
) -> dict[str, float | bool]:
    # Derived from darktable's GPLv3 AgX implementation:
    # https://github.com/darktable-org/darktable/blob/master/src/iop/agx.c
    # and its OpenCL kernel:
    # https://github.com/darktable-org/darktable/blob/master/data/kernels/agx.cl
    range_ev = max(1.0, white_ev - black_ev)
    pivot_x = _clamp_float(pivot_x, EPS, 1.0 - EPS)
    pivot_y = max(EPS, pivot_y_linear) ** (1.0 / gamma)
    target_black = _clamp_float(target_black_linear, 0.0, 0.15) ** (1.0 / gamma) if target_black_linear > 0.0 else 0.0
    target_white = 1.0
    range_adjusted_slope = contrast * (range_ev / 16.5)
    # Contrast compensation (darktable): keep the pivot's slope in LINEAR output terms
    # constant when gamma / pivot_y move, so "contrast" means the same thing whether the
    # adaptive gamma engaged or not.
    pivot_y_default = 0.18 ** (1.0 / DEFAULT_CURVE_GAMMA)
    derivative_current = gamma * max(EPS, pivot_y) ** (gamma - 1.0)
    derivative_default = DEFAULT_CURVE_GAMMA * pivot_y_default ** (DEFAULT_CURVE_GAMMA - 1.0)
    slope = range_adjusted_slope / (derivative_current / derivative_default)

    # Latitude: a linear mid segment through the pivot. With zero latitude the curve is
    # Troy's pure sigmoid (toe meets shoulder at mid gray) — which converges channels and
    # washes chroma from mid gray UP. Scene-driven latitude pushes the shoulder start
    # above the subject's colorful range in bright wide-DR scenes. Clamps reserve
    # MIN_SEGMENT_X of x-run for both toe and shoulder AND keep the transition y inside
    # the display range, using the SAME clamped latitude for x and y so the transitions
    # stay on the linear segment.
    lat_lo_x = _clamp_float(max(0.0, latitude_lo_ev) / range_ev, 0.0, max(0.0, pivot_x - MIN_SEGMENT_X))
    lat_hi_x = _clamp_float(max(0.0, latitude_hi_ev) / range_ev, 0.0, max(0.0, 1.0 - pivot_x - MIN_SEGMENT_X))
    if slope > EPS:
        lat_lo_x = min(lat_lo_x, max(0.0, (pivot_y - target_black - 0.02) / slope))
        lat_hi_x = min(lat_hi_x, max(0.0, (0.95 - pivot_y) / slope))

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

    shoulder_transition_x = min(1.0 - MIN_SEGMENT_X, pivot_x + lat_hi_x)
    shoulder_transition_y = min(1.0 - EPS, pivot_y + slope * (shoulder_transition_x - pivot_x))
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
        "gamma": gamma,
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


@lru_cache(maxsize=32)
def curve_params(
    black_ev: float = -10.0,
    white_ev: float = 6.5,
    contrast: float = 3.0,
    toe_power: float = 1.5,
    shoulder_power: float = 3.3,
    latitude_lo_ev: float = 0.0,
    latitude_hi_ev: float = 0.0,
    pivot_ev_offset: float = 0.0,
    target_black_linear: float = 0.0,
    keep_pivot_diagonal: bool = True,
    curve_gamma: float = DEFAULT_CURVE_GAMMA,
) -> dict[str, float | bool]:
    """AgX curve parameterization with scene-adaptive pivot and adaptive gamma.

    pivot_ev_offset moves the point of maximum contrast (in EV relative to mid gray)
    toward the subject; the pivot's OUTPUT is taken from the unshifted reference curve
    at the same input, so overall brightness is preserved — only the contrast
    distribution moves. The internal y gamma is then solved to put the pivot on the
    curve diagonal (darktable's "keep the pivot on the diagonal"), which keeps the
    curve S-shaped and the toe/shoulder powers effective across narrow-DR and
    dark-scene windows that previously degenerated into fallback power curves.
    """
    black_ev = float(black_ev)
    white_ev = float(white_ev)
    range_ev = max(1.0, white_ev - black_ev)

    # Reference curve: unshifted pivot at mid gray, original fixed gamma. Used to read
    # the brightness-preserving output for a shifted pivot.
    pivot_x0 = _clamp_float(-black_ev / range_ev, EPS, 1.0 - EPS)
    pivot_ev_offset = _clamp_float(pivot_ev_offset, black_ev + MIN_SEGMENT_X * range_ev, white_ev - MIN_SEGMENT_X * range_ev)
    pivot_x = _clamp_float((pivot_ev_offset - black_ev) / range_ev, 0.10, 0.90)

    if abs(pivot_ev_offset) > 1e-6:
        reference = _build_curve_params(
            black_ev, white_ev, contrast, toe_power, shoulder_power,
            latitude_lo_ev, latitude_hi_ev,
            pivot_x0, 0.18, DEFAULT_CURVE_GAMMA, target_black_linear,
        )
        y_encoded = float(apply_curve(np.asarray([pivot_x], dtype=np.float32), reference)[0])
        pivot_y_linear = _clamp_float(y_encoded ** DEFAULT_CURVE_GAMMA, 0.02, 0.50)
    else:
        pivot_y_linear = 0.18

    # darktable exposes this as "keep the pivot on the diagonal". Its scene-referred
    # default keeps the historical 2.2 curve gamma; callers selecting the automatic
    # option retain the older dngscan behavior.
    if keep_pivot_diagonal and pivot_x < 1.0 - EPS and 0.0 < pivot_y_linear < 1.0:
        gamma = _clamp_float(
            float(np.log(pivot_y_linear) / np.log(pivot_x)), 1.5, 5.0
        )
    else:
        gamma = _clamp_float(curve_gamma, 0.01, 100.0)

    return _build_curve_params(
        black_ev, white_ev, contrast, toe_power, shoulder_power,
        latitude_lo_ev, latitude_hi_ev,
        pivot_x, pivot_y_linear, gamma, target_black_linear,
    )


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


@lru_cache(maxsize=16)
def _effective_outset_key(purity: float, rotation_reversal: float) -> Any:
    """Effective outset from two scalars (darktable-inspired primaries controls).

    rotation_reversal blends the Blender outset toward inv(inset), undoing the inset's
    deliberate hue rotation; purity blends the result between identity (no purity
    restoration, muted) and full strength (>1 extrapolates, punchier)."""
    base = np.asarray(AGX_OUTSET_REC2020, dtype=np.float64)
    if rotation_reversal != 0.0:
        inv_inset = np.linalg.inv(np.asarray(AGX_INSET_REC2020, dtype=np.float64))
        base = base + float(rotation_reversal) * (inv_inset - base)
    if purity != 1.0:
        identity = np.eye(3, dtype=np.float64)
        base = identity + float(purity) * (base - identity)
    return base


def effective_outset(outset_matrix: Any, purity: float = 1.0, rotation_reversal: float = 0.0) -> Any:
    if purity == 1.0 and rotation_reversal == 0.0:
        return outset_matrix
    return _effective_outset_key(round(float(purity), 4), round(float(rotation_reversal), 4))


def apply_core(rgb_rec2020: Any, plan: Any, inset_matrix: Any, outset_matrix: Any) -> Any:
    """AgX per Blender/EaryChow reference order, in Rec.2020 working space:

    guard rail -> inset (rotation+attenuation) -> log2 window -> sigmoid ->
    linearize -> hue mix (plan.hue_keep of per-channel shift) -> outset in LINEAR light.

    Deviations from the reference, all deliberate: the endpoint-normalized log2 window
    and C1 sigmoid parameters come from the scene plan while EV=0 remains the calibrated
    mid-gray pivot; the scene DRT uses darktable's default fixed internal gamma, whereas
    the legacy branch retains optional diagonal-pivot gamma; and the outset can be
    reshaped by the plan's purity / rotation-reversal scalars (base matches Blender).
    """
    hue_keep = _clamp_float(float(getattr(plan, "hue_keep", AGX_HUE_KEEP)), 0.0, 1.0)
    outset = effective_outset(
        outset_matrix,
        float(getattr(plan, "outset_purity", 1.0)),
        float(getattr(plan, "outset_rotation_reversal", 0.0)),
    )
    rgb = compress_into_gamut(rgb_rec2020.astype(np.float32, copy=False))
    inset = _apply_matrix3(rgb, inset_matrix)
    pre_hue = _rgb_to_hsv(np.maximum(inset, 0.0))[:, 0] if hue_keep < 0.999 else None
    if bool(getattr(plan, "use_c1_endpoints", False)):
        # The DRT derives endpoints from luminance-only scene measurements but maps each
        # AgX-inset channel through the same endpoint-normalized C1 curve, preserving
        # the per-channel path-to-white.
        from .drt import apply_c1_endpoints

        linear = apply_c1_endpoints(np.log2(np.maximum(inset / 0.18, EPS)), plan)
    else:
        params = curve_params(
            round(plan.black_ev, 3),
            round(plan.white_ev, 3),
            round(plan.contrast, 3),
            round(plan.toe_power, 3),
            round(plan.shoulder_power, 3),
            round(float(getattr(plan, "latitude_lo_ev", 0.0)), 3),
            round(float(getattr(plan, "latitude_hi_ev", 0.0)), 3),
            round(float(getattr(plan, "pivot_ev_offset", 0.0)), 3),
            round(float(getattr(plan, "target_black_linear", 0.0)), 4),
        )
        log_encoded = (np.log2(np.maximum(inset / 0.18, EPS)) - float(params["black_ev"])) / float(params["range_ev"])
        log_encoded = np.clip(log_encoded, 0.0, 1.0)
        curved = apply_curve(log_encoded, params)
        brightness = max(EPS, float(getattr(plan, "view_brightness", 1.0)))
        if abs(brightness - 1.0) > 1e-6:
            curved = np.power(np.maximum(curved, 0.0), 1.0 / brightness)
        linear = np.power(np.maximum(curved, 0.0), float(params["gamma"]))
    brightness = max(EPS, float(getattr(plan, "view_brightness", 1.0)))
    if bool(getattr(plan, "use_c1_endpoints", False)) and abs(brightness - 1.0) > 1e-6:
        # Mirrors darktable's display-referred "brightness" look control. It raises
        # only the interior of the curve, preserving true black and target white.
        linear = np.power(np.maximum(linear, 0.0), 1.0 / brightness)
    if pre_hue is not None:
        linear = _mix_hue(linear, pre_hue, hue_keep)
    return _apply_matrix3(linear, outset).astype(np.float32)
