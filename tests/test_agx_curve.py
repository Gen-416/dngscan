# SPDX-License-Identifier: GPL-3.0-or-later
"""AgX curve: inversion protection, adaptive pivot/gamma, target black, outset presets."""
from __future__ import annotations

import unittest

import numpy as np

from dngscan.agx import (
    AGX_INSET_REC2020, AGX_OUTSET_REC2020, AGX_PRIMARIES_PRESETS, MIN_SEGMENT_X,
    apply_core, apply_curve, curve_params, effective_outset,
)


# The X-T2 greycard scene that originally collapsed the shoulder: narrow highlights,
# pivot far right, latitude pushing the transition past the window edge.
NARROW_SCENE = dict(
    black_ev=-5.96, white_ev=1.82, contrast=3.03,
    toe_power=1.23, shoulder_power=3.30,
    latitude_lo_ev=0.0, latitude_hi_ev=1.94,
)


class _PlanStub:
    black_ev = -6.5
    white_ev = 4.0
    contrast = 3.0
    toe_power = 1.5
    shoulder_power = 3.3
    latitude_lo_ev = 0.0
    latitude_hi_ev = 1.0
    punch_strength = 0.0
    tone_core = "agx"


class CurveInversionTest(unittest.TestCase):
    def test_shoulder_keeps_minimum_run(self) -> None:
        p = curve_params(**NARROW_SCENE)
        self.assertLessEqual(float(p["shoulder_transition_x"]), 1.0 - MIN_SEGMENT_X + 1e-9)
        # transition y must sit on the linear segment (consistent x/y clamping)
        expected_y = float(p["slope"]) * float(p["shoulder_transition_x"]) + float(p["intercept"])
        self.assertAlmostEqual(float(p["shoulder_transition_y"]), expected_y, places=5)

    def test_curve_reaches_white_and_black(self) -> None:
        for kwargs in (NARROW_SCENE, dict(black_ev=-10.0, white_ev=6.5, contrast=3.0,
                                          toe_power=1.5, shoulder_power=3.3)):
            p = curve_params(**kwargs)
            x = np.linspace(0.0, 1.0, 2001, dtype=np.float32)
            y = apply_curve(x, p)
            self.assertGreater(float(y[-1]), 0.985, msg=str(kwargs))
            self.assertLess(float(y[0]), float(p["target_black"]) + 0.02, msg=str(kwargs))

    def test_curve_monotone_no_jump(self) -> None:
        p = curve_params(**NARROW_SCENE)
        x = np.linspace(0.0, 1.0, 4001, dtype=np.float32)
        y = apply_curve(x, p)
        dy = np.diff(y.astype(np.float64))
        self.assertGreaterEqual(float(dy.min()), -1e-6)
        # no near-discontinuity: largest step bounded (the old collapsed shoulder
        # jumped ~0.2 across one sample)
        self.assertLess(float(dy.max()), 0.01)

    def test_adaptive_gamma_puts_pivot_near_diagonal(self) -> None:
        p = curve_params(black_ev=-10.0, white_ev=6.5, contrast=3.0, toe_power=1.5, shoulder_power=3.3)
        pivot_x = -(-10.0) / 16.5
        pivot_y = float(p["slope"]) * pivot_x + float(p["intercept"])
        self.assertLess(abs(pivot_y - pivot_x), 0.02)
        # mid gray still maps to 0.18 linear at the pivot
        self.assertAlmostEqual(pivot_y ** float(p["gamma"]), 0.18, places=3)


class AdaptivePivotTest(unittest.TestCase):
    def test_zero_offset_unchanged_reference(self) -> None:
        a = curve_params(-8.0, 4.0, 3.0, 1.5, 3.3)
        b = curve_params(-8.0, 4.0, 3.0, 1.5, 3.3, pivot_ev_offset=0.0)
        self.assertEqual(a, b)

    def test_shifted_pivot_preserves_brightness_at_pivot(self) -> None:
        offset = -0.9
        base = curve_params(-8.0, 4.0, 3.0, 1.5, 3.3)
        shifted = curve_params(-8.0, 4.0, 3.0, 1.5, 3.3, pivot_ev_offset=offset)
        x = np.asarray([(offset + 8.0) / 12.0], dtype=np.float32)
        y_base = float(apply_curve(x, base)[0]) ** float(base["gamma"])
        y_shift = float(apply_curve(x, shifted)[0]) ** float(shifted["gamma"])
        self.assertAlmostEqual(y_base, y_shift, delta=0.01)

    def test_shifted_pivot_raises_contrast_at_subject(self) -> None:
        offset = -1.2
        base = curve_params(-8.0, 4.0, 3.0, 1.5, 3.3)
        shifted = curve_params(-8.0, 4.0, 3.0, 1.5, 3.3, pivot_ev_offset=offset)
        x0 = (offset + 8.0) / 12.0
        xs = np.asarray([x0 - 0.01, x0 + 0.01], dtype=np.float32)
        def linear_slope(p):
            ys = apply_curve(xs, p).astype(np.float64) ** float(p["gamma"])
            return (ys[1] - ys[0]) / 0.02
        self.assertGreater(linear_slope(shifted), linear_slope(base))


class TargetBlackTest(unittest.TestCase):
    def test_target_black_lifts_floor(self) -> None:
        p = curve_params(-8.0, 4.0, 3.0, 1.5, 3.3, target_black_linear=0.03)
        x = np.linspace(0.0, 1.0, 501, dtype=np.float32)
        y_linear = apply_curve(x, p).astype(np.float64) ** float(p["gamma"])
        self.assertGreater(float(y_linear.min()), 0.02)
        self.assertGreater(float(y_linear[-1]), 0.95)


class OutsetPresetTest(unittest.TestCase):
    def test_base_is_identity_passthrough(self) -> None:
        m = effective_outset(AGX_OUTSET_REC2020, *AGX_PRIMARIES_PRESETS["base"])
        self.assertIs(m, AGX_OUTSET_REC2020)

    def test_punchy_increases_chroma(self) -> None:
        rgb = np.asarray([[0.30, 0.12, 0.06]], dtype=np.float32)
        plan = _PlanStub()
        base = apply_core(rgb, plan, AGX_INSET_REC2020, AGX_OUTSET_REC2020)
        plan_p = _PlanStub()
        plan_p.outset_purity, plan_p.outset_rotation_reversal = AGX_PRIMARIES_PRESETS["punchy"]
        punchy = apply_core(rgb, plan_p, AGX_INSET_REC2020, AGX_OUTSET_REC2020)
        def spread(v):
            return float(v.max() - v.min())
        self.assertGreater(spread(punchy[0]), spread(base[0]))

    def test_smooth_differs_from_base(self) -> None:
        rgb = np.asarray([[0.30, 0.12, 0.06], [0.05, 0.20, 0.35]], dtype=np.float32)
        plan_s = _PlanStub()
        plan_s.outset_purity, plan_s.outset_rotation_reversal = AGX_PRIMARIES_PRESETS["smooth"]
        base = apply_core(rgb, _PlanStub(), AGX_INSET_REC2020, AGX_OUTSET_REC2020)
        smooth = apply_core(rgb, plan_s, AGX_INSET_REC2020, AGX_OUTSET_REC2020)
        self.assertGreater(float(np.abs(base - smooth).max()), 1e-4)

    def test_neutral_axis_preserved_by_presets(self) -> None:
        gray = np.asarray([[0.18, 0.18, 0.18]], dtype=np.float32)
        for name, (purity, rot) in AGX_PRIMARIES_PRESETS.items():
            plan = _PlanStub()
            plan.outset_purity, plan.outset_rotation_reversal = purity, rot
            out = apply_core(gray, plan, AGX_INSET_REC2020, AGX_OUTSET_REC2020)[0]
            self.assertLess(float(out.max() - out.min()), 5e-3, msg=name)


class HueKeepTest(unittest.TestCase):
    def test_hue_keep_extremes_differ(self) -> None:
        rgb = np.asarray([[0.45, 0.08, 0.04]], dtype=np.float32)
        plan_lo = _PlanStub()
        plan_lo.hue_keep = 0.0
        plan_hi = _PlanStub()
        plan_hi.hue_keep = 1.0
        lo = apply_core(rgb, plan_lo, AGX_INSET_REC2020, AGX_OUTSET_REC2020)
        hi = apply_core(rgb, plan_hi, AGX_INSET_REC2020, AGX_OUTSET_REC2020)
        self.assertGreater(float(np.abs(lo - hi).max()), 1e-4)

    def test_default_matches_explicit_04(self) -> None:
        rgb = np.asarray([[0.45, 0.08, 0.04]], dtype=np.float32)
        plan = _PlanStub()
        plan_04 = _PlanStub()
        plan_04.hue_keep = 0.4
        a = apply_core(rgb, plan, AGX_INSET_REC2020, AGX_OUTSET_REC2020)
        b = apply_core(rgb, plan_04, AGX_INSET_REC2020, AGX_OUTSET_REC2020)
        self.assertTrue(np.array_equal(a, b))


class LookOverrideTest(unittest.TestCase):
    def test_plan_overrides_from_look_fields(self) -> None:
        from dngscan import look as look_engine

        field = look_engine.LOOK_FIELDS["classic"]
        self.assertIsNone(field.agx_hue_keep)
        self.assertEqual(look_engine.agx_plan_overrides("classic"), {})
        self.assertEqual(look_engine.agx_plan_overrides("does_not_exist"), {})

        velvia = look_engine.agx_plan_overrides("fuji_velvia")
        self.assertAlmostEqual(velvia["hue_keep"], 0.55)
        half = look_engine.agx_plan_overrides("fuji_velvia", 0.5)
        self.assertAlmostEqual(half["hue_keep"], 0.4 + 0.5 * (0.55 - 0.4))

        neg = look_engine.agx_plan_overrides("fuji_classic_neg")
        self.assertAlmostEqual(neg["target_black_linear"], 0.022)

        import dataclasses

        faded = dataclasses.replace(field, agx_hue_keep=0.6, agx_target_black=0.025)
        look_engine.LOOK_FIELDS["_test_faded"] = faded
        try:
            overrides = look_engine.agx_plan_overrides("_test_faded")
            self.assertAlmostEqual(overrides["hue_keep"], 0.6)
            self.assertAlmostEqual(overrides["target_black_linear"], 0.025)
        finally:
            del look_engine.LOOK_FIELDS["_test_faded"]


class TonePlanPivotTest(unittest.TestCase):
    def test_dark_median_pulls_pivot(self) -> None:
        from dngscan.models import Analysis, RawBundle, ToneCompressionPlan
        from dngscan.tone import build_tone_compression_plan
        from pathlib import Path

        analysis = Analysis(
            channel_ids=[0, 1, 2],
            labels={0: "R", 1: "G", 2: "B"},
            ceilings={0: 1000, 1: 1000, 2: 1000},
            ceil_spike_counts={0: 0, 1: 0, 2: 0},
            ceil_near_counts={0: 0, 1: 0, 2: 0},
            ceil_spike_ok={0: False, 1: False, 2: False},
            fullwell_channel_ids=[0, 1, 2],
            fullwell_note="test",
            saturation_levels={0: 1000, 1: 1000, 2: 1000},
            channel_fullwell={0: 1000, 1: 1000, 2: 1000},
            channel_thresholds={0: 996, 1: 996, 2: 996},
            fullwell=1000,
            threshold=996,
            clip_pct={0: 0.0, 1: 0.0, 2: 0.0},
            cfa_cell_supported=True,
            cell_union_pct=0.0,
            cell_ge2_of_clipped_pct=0.0,
            cell_k_of_clipped_pct={1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0},
            cell_k_of_all_pct={1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0},
            ev_p1=-8.0,
            ev_raw_p1=-8.0,
            ev_median=-4.5,
            ev_p99=-1.0,
            ev_p999=-0.5,
            ev_dr_p1_p999=7.5,
            ev_floor_hit_pct=0.0,
            median_vs_gray_ev=-2.0,
            median_y=0.04,
            noise_floor=0.002,
            usable_dr_ev=8.0,
            snr_curves={},
            snr1_dr={},
            snr1_stop={},
            gamut_out_pct={"sRGB": 0.0, "Display P3": 0.0, "Rec2020": 0.0},
            bright_pixel_pct=0.0,
            survivor_channel="R",
            container_bits_est=14,
            usable_dr_eff_ev=8.0,
        )
        bundle = RawBundle(
            path=Path("x.dng"),
            raw_image=np.zeros((4, 4), dtype=np.uint16),
            raw_colors=np.zeros((4, 4), dtype=np.uint8),
            xyz_render=np.zeros((2, 2, 3), dtype=np.float32),
            render_scale=65535.0,
            scene_rec2020_render=np.full((2, 2, 3), 0.04, dtype=np.float32),
            scene_scale=65535.0,
            white_level=16383,
            black_levels=[1000.0, 1000.0, 1000.0],
            camera_wb=[1.0, 1.0, 1.0, 0.0],
            color_desc="RGB",
            raw_pattern=[[0, 1], [1, 2]],
            camera_white_levels=[16383, 16383, 16383],
            exposure_gain=1.0,
        )
        plan = build_tone_compression_plan(bundle, analysis, "Rec2020")
        self.assertLess(plan.pivot_ev_offset, -0.3)


if __name__ == "__main__":
    unittest.main()
