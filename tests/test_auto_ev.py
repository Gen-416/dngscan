# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import math
import unittest

from dngscan.auto_ev import (
    anchored_median_ev,
    compute_auto_ev,
    is_ev_auto,
    median_align_ev,
    parse_ev_value,
    resolve_export_ev,
)
from dngscan.models import Analysis, RawBundle
from dngscan.tone import compute_exposure_gain


def _minimal_analysis(median_vs_gray_ev: float) -> Analysis:
    return Analysis(
        channel_ids=[0, 1, 2, 3],
        labels={0: "R", 1: "G1", 2: "B", 3: "G2"},
        ceilings={},
        ceil_spike_counts={},
        ceil_near_counts={},
        ceil_spike_ok={},
        fullwell_channel_ids=[0, 1, 3],
        fullwell_note="",
        saturation_levels={},
        channel_fullwell={},
        channel_thresholds={},
        fullwell=16000,
        threshold=15996,
        clip_pct={0: 0.0, 1: 0.0, 2: 0.0, 3: 0.0},
        cfa_cell_supported=True,
        cell_union_pct=0.0,
        cell_ge2_of_clipped_pct=0.0,
        cell_k_of_clipped_pct={},
        cell_k_of_all_pct={},
        ev_p1=-8.0,
        ev_raw_p1=-8.0,
        ev_median=-2.0,
        ev_p99=-0.5,
        ev_p999=-0.2,
        ev_dr_p1_p999=7.8,
        ev_floor_hit_pct=0.0,
        median_vs_gray_ev=median_vs_gray_ev,
        median_y=0.05,
        noise_floor=0.002,
        usable_dr_ev=8.5,
        snr_curves={},
        snr1_dr={},
        snr1_stop={},
        gamut_out_pct={"sRGB": 0.0, "P3": 0.0, "Rec2020": 0.0},
        bright_pixel_pct=0.5,
        survivor_channel="B",
        container_bits_est=14,
        prior_id=None,
        gain_e_per_dn=None,
        noise_floor_e=None,
        prior_read_noise_e=None,
        prior_pdr_ev=None,
        usable_dr_eff_ev=8.5,
        health_lag1_corr=0.0,
        health_hist_empty_pct=0.0,
    )


def test_parse_ev_auto_token():
    assert parse_ev_value("auto") == "auto"
    assert parse_ev_value("AUTO") == "auto"
    assert parse_ev_value("1.25") == 1.25
    assert is_ev_auto("auto")


def test_median_align_ev_agx():
    analysis = _minimal_analysis(-1.51)
    ev = median_align_ev("agx", analysis)
    base = compute_exposure_gain("agx", 0.0)
    assert abs(ev - (-analysis.median_vs_gray_ev - math.log2(base))) < 1e-4
    assert abs(anchored_median_ev("agx", analysis, ev)) < 1e-4


def test_median_align_ev_neutral():
    analysis = _minimal_analysis(-1.0)
    ev = median_align_ev("neutral", analysis)
    assert abs(ev - 1.0) < 1e-6
    assert abs(anchored_median_ev("neutral", analysis, ev)) < 1e-6


def test_resolve_export_ev_manual():
    bundle = RawBundle(
        path=__file__,
        raw_image=None,
        raw_colors=None,
        xyz_render=None,
        render_scale=1.0,
        scene_rec2020_render=None,
        scene_scale=1.0,
        white_level=16383,
        black_levels=[1024.0, 1024.0, 1024.0, 1024.0],
        camera_wb=[1.0, 1.0, 1.0, 1.0],
        color_desc="RGBG",
        raw_pattern=[[0, 1], [1, 2]],
        camera_white_levels=[16383.0, 16383.0, 16383.0, 16383.0],
    )
    analysis = _minimal_analysis(-1.0)
    ev, auto = resolve_export_ev(0.5, bundle, analysis, "agx", "p3")
    assert ev == 0.5
    assert auto is None


class AutoEvTest(unittest.TestCase):
    test_parse_ev_auto_token = staticmethod(test_parse_ev_auto_token)
    test_median_align_ev_agx = staticmethod(test_median_align_ev_agx)
    test_median_align_ev_neutral = staticmethod(test_median_align_ev_neutral)
    test_resolve_export_ev_manual = staticmethod(test_resolve_export_ev_manual)


if __name__ == "__main__":
    unittest.main()
