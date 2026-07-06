# SPDX-License-Identifier: GPL-3.0-or-later
"""Content-aware EV suggestion: median → 18% gray with highlight safety."""
from __future__ import annotations

import math
from typing import Any

from ._deps import np
from .color import RGB_TO_XYZ, luminance_from_rec2020, output_gamut_space
from .constants import EPS
from .models import Analysis, AutoEvResult, RawBundle, ToneCompressionPlan
from .render import apply_agx_core, rec2020_to_output
from .tone import compute_exposure_gain, plan_for_mode, scene_rec2020_to_float

EV_AUTO_TOKEN = "auto"


def parse_ev_value(value: str | float) -> float | str:
    if isinstance(value, str) and value.strip().lower() == EV_AUTO_TOKEN:
        return EV_AUTO_TOKEN
    return float(value)


def is_ev_auto(value: str | float) -> bool:
    return isinstance(value, str) and value.strip().lower() == EV_AUTO_TOKEN


def median_align_ev(mode: str, analysis: Analysis) -> float:
    """EV compensation that places the scene median on 18% gray after the mode anchor."""
    base_gain = compute_exposure_gain(mode, 0.0)
    return float(-analysis.median_vs_gray_ev - math.log2(max(base_gain, EPS)))


def anchored_median_ev(mode: str, analysis: Analysis, ev: float) -> float:
    gain = compute_exposure_gain(mode, ev)
    return float(analysis.median_vs_gray_ev + math.log2(max(gain, EPS)))


def output_highlight_stats(rgb_linear: Any, gamut: str) -> tuple[float, float, float, float]:
    """(p99.9 luma%, p99.9 max-channel%, clipped-pixel%, near-white%) of an output-linear buffer."""
    rgb = np.clip(np.nan_to_num(rgb_linear, nan=0.0, posinf=1.0, neginf=0.0), 0.0, 1.0)
    matrix = RGB_TO_XYZ[output_gamut_space(gamut)]
    y = matrix[1, 0] * rgb[:, 0] + matrix[1, 1] * rgb[:, 1] + matrix[1, 2] * rgb[:, 2]
    y = np.clip(np.nan_to_num(y, nan=0.0, posinf=1.0, neginf=0.0), 0.0, 1.0)
    max_channel = np.max(rgb, axis=1)
    return (
        float(np.percentile(y, 99.9) * 100.0),
        float(np.percentile(max_channel, 99.9) * 100.0),
        float(np.mean(np.any(rgb >= np.float32(0.999), axis=1)) * 100.0),
        float(np.mean(max_channel >= np.float32(0.956)) * 100.0),
    )


def output_highlight_margin(
    rgb_linear: Any, gamut: str, baseline: tuple[float, float, float, float] | None = None
) -> float:
    """Positive margin means headroom before highlight risk thresholds.

    With `baseline` (the stats at the starting EV), the clip/near-white limits become
    growth budgets relative to that baseline: clipping that already exists in the capture
    (lamps, speculars — light sources are SUPPOSED to clip) does not count against the
    boost; only NEW clipping does. The luma/max-channel percentile limits stay absolute."""
    if np is None:
        return 0.0
    y_p999, max_p999, clip_pct, near_pct = output_highlight_stats(rgb_linear, gamut)
    clip_limit = 0.03
    near_limit = 0.25
    if baseline is not None:
        clip_limit = max(clip_limit, baseline[2] + 0.03)
        near_limit = max(near_limit, baseline[3] + 0.25)
    margin_luma = 92.0 - y_p999
    margin_rgb = 96.0 - max_p999
    margin_clip = clip_limit - clip_pct
    margin_near = near_limit - near_pct
    return float(min(margin_luma, margin_rgb, margin_clip * 10.0, margin_near))


def render_sample_linear_output(
    bundle: RawBundle,
    analysis: Analysis | None,
    gamut: str,
    ev: float,
    sample_rec2020: Any,
    tone_plan: ToneCompressionPlan | None = None,
) -> Any:
    from .grade import RENDER_MODE

    bundle.exposure_gain = compute_exposure_gain(RENDER_MODE, ev)
    rec = scene_rec2020_to_float(sample_rec2020, bundle.scene_scale, bundle.exposure_gain)
    plan = tone_plan if tone_plan is not None else (
        plan_for_mode(bundle, analysis, RENDER_MODE, gamut) if analysis is not None else None
    )
    return rec2020_to_output(apply_agx_core(rec, plan), gamut)


def max_safe_ev(
    bundle: RawBundle,
    analysis: Analysis | None,
    gamut: str,
    from_ev: float = 0.0,
    max_samples: int = 220_000,
    search_hi: float = 3.0,
) -> float:
    """Largest EV (>= from_ev) whose preview-scale output stays below highlight thresholds."""
    from .grade import RENDER_MODE

    if np is None:
        return float(from_ev)
    flat = bundle.scene_rec2020_render.reshape(-1, bundle.scene_rec2020_render.shape[-1])
    step = max(1, int(math.ceil(flat.shape[0] / max_samples)))
    sample_rgb = flat[::step, :3]
    original_gain = bundle.exposure_gain

    baseline_stats: tuple[float, float, float, float] | None = None

    def margin_at(ev: float) -> float:
        rgb = render_sample_linear_output(bundle, analysis, gamut, ev, sample_rgb)
        return output_highlight_margin(rgb, gamut, baseline_stats)

    try:
        baseline_rgb = render_sample_linear_output(bundle, analysis, gamut, from_ev, sample_rgb)
        baseline_stats = output_highlight_stats(baseline_rgb, gamut)
        if output_highlight_margin(baseline_rgb, gamut, baseline_stats) <= 0.0:
            return float(from_ev)

        low = float(from_ev)
        high = low + 0.5
        while margin_at(high) > 0.0 and high < from_ev + search_hi:
            low = high
            high += 0.5

        if margin_at(high) > 0.0:
            return float(high)

        for _ in range(6):
            mid = (low + high) * 0.5
            if margin_at(mid) > 0.0:
                low = mid
            else:
                high = mid
        return float(low)
    finally:
        bundle.exposure_gain = original_gain


def compute_auto_ev(
    bundle: RawBundle,
    analysis: Analysis,
    gamut: str = "p3",
    baseline_ev: float = 0.0,
) -> AutoEvResult:
    """Boost toward 18% gray median when scene is dark; never darken high-key captures.

    Highlight cap limits upward boost only. Scenes already at or above the anchor
    (negative median_align target) stay at baseline_ev — auto does not gray-world
    snow/high-key into mid gray.
    """
    from .grade import RENDER_MODE

    mode = RENDER_MODE
    target = median_align_ev(mode, analysis)
    cap = max_safe_ev(bundle, analysis, gamut, from_ev=baseline_ev)
    boost_target = max(target, baseline_ev)
    ev = min(boost_target, cap)
    limited = boost_target > cap + 1e-6
    return AutoEvResult(
        ev=float(ev),
        ev_median_target=float(target),
        ev_boost=float(ev - baseline_ev),
        highlight_limited=limited,
        highlight_cap_ev=float(cap),
        anchored_median_ev=anchored_median_ev(mode, analysis, ev),
    )


def resolve_export_ev(
    ev: str | float,
    bundle: RawBundle,
    analysis: Analysis,
    gamut: str,
) -> tuple[float, AutoEvResult | None]:
    if not is_ev_auto(ev):
        return float(ev), None
    result = compute_auto_ev(bundle, analysis, gamut)
    return result.ev, result


def auto_ev_overlay_lines(result: AutoEvResult) -> list[str]:
    lines = [f"EV auto {result.ev_boost:+.2f}"]
    if result.ev_median_target < -1e-6 and result.ev_boost < 1e-6:
        lines.append("中灰已高于锚定 · 保持 EV 0")
    elif result.highlight_limited:
        lines.append(
            f"中灰目标 {result.ev_median_target:+.2f} · 高光限制至 {result.ev:+.2f}"
        )
    else:
        lines.append(f"中灰对齐 18% ({result.anchored_median_ev:+.2f} EV)")
    return lines
