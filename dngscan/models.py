# SPDX-License-Identifier: GPL-3.0-or-later
"""Core datatypes passed through the dngscan pipeline."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .constants import DEFAULT_GAINMAP_SCALE, DEFAULT_HDR_HEADROOM_EV


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
    wb_mode: str = "camera"
    daylight_wb: list[float] | None = None
    shot_make: str | None = None
    shot_model: str | None = None
    shot_iso: int | None = None
    # Half-resolution, orientation-correct RGB soft clip masks in raw/CFA space.
    # Shape is (H, W, 3), aligned to scene_rec2020_render when scene_half_size=True.
    # Full-resolution renders resize this mask to the render buffer on demand.
    clip_masks: Any | None = None


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
    prior_id: str | None = None
    gain_e_per_dn: float | None = None
    noise_floor_e: float | None = None
    prior_read_noise_e: float | None = None
    prior_pdr_ev: float | None = None
    usable_dr_eff_ev: float = float("nan")
    health_lag1_corr: float = float("nan")
    health_hist_empty_pct: float = float("nan")


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
    # Linear latitude around the pivot (EV): shoulder starts latitude_hi_ev above mid
    # gray instead of at it, keeping bright subject colors out of the channel-converging
    # shoulder; a small lower run keeps upper shadows off the toe. Zero = pure sigmoid.
    latitude_lo_ev: float = 0.0
    latitude_hi_ev: float = 0.0
    # Scene-driven purity compensation applied after the AgX curve (see dngscan/punch.py).
    # 0 = identity (night/high-ISO scenes gate to exactly zero).
    punch_strength: float = 0.0
    # Tone core selector: "agx" keeps inset/outset AgX, "lum" uses luminance-ratio shoulder.
    tone_core: str = "agx"
    # Norm for the luminance core: "y", "power", or "max".
    lum_norm: str = "y"


@dataclass
class AutoEvResult:
    ev: float
    ev_median_target: float
    ev_boost: float
    highlight_limited: bool
    highlight_cap_ev: float
    anchored_median_ev: float


@dataclass
class GainMapMetadata:
    headroom: float
    gamma: float = 1.0
    min_gain: float = 0.0
    max_gain: float = DEFAULT_HDR_HEADROOM_EV
    hdr_capacity_min: float = 0.0
    hdr_capacity_max: float = DEFAULT_HDR_HEADROOM_EV
    gainmap_scale: int = DEFAULT_GAINMAP_SCALE
