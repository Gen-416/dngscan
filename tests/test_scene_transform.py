# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for scene-linear pre-AgX transforms."""

from __future__ import annotations

import unittest

import dngscan as dg


class SceneTransformTests(unittest.TestCase):
    def test_strength_zero_is_identity(self) -> None:
        rgb = dg.np.asarray([[1.4, 1.0, 0.25], [0.2, 0.2, 0.2]], dtype=dg.np.float32)
        out = dg.apply_scene_transform_rec2020(rgb, "arri_skin_d55", 0.0)
        self.assertTrue(dg.np.allclose(out, rgb))

    def test_neutral_axis_is_preserved(self) -> None:
        rgb = dg.np.asarray([[0.18, 0.18, 0.18], [2.0, 2.0, 2.0]], dtype=dg.np.float32)
        out = dg.apply_scene_transform_rec2020(rgb, "arri_skin_d55", 1.0)
        self.assertTrue(dg.np.allclose(out, rgb, atol=1e-6))

    def test_skin_region_changes_colour(self) -> None:
        preset = dg.SCENE_TRANSFORMS["arri_skin_d55"]
        mu = preset.regions[0].mu_rg_bg
        rgb = dg.np.asarray([[mu[0], 1.0, mu[1]]], dtype=dg.np.float32)
        out = dg.apply_scene_transform_rec2020(rgb, "arri_skin_d55", 1.0)
        self.assertGreater(float(dg.np.max(dg.np.abs(out - rgb))), 1e-4)


    def test_wb_adaptation_identity_for_daylight(self) -> None:
        from dngscan.scene_transform import wb_adaptation_ratios

        self.assertIsNone(wb_adaptation_ratios("daylight", [1.5, 1.0, 2.3], [2.6, 1.3, 2.3]))
        self.assertIsNone(wb_adaptation_ratios("camera", None, [2.6, 1.3, 2.3]))
        # applied == daylight -> identity
        self.assertIsNone(wb_adaptation_ratios("camera", [2.6, 1.3, 2.3], [2.6, 1.3, 2.3]))

    def test_wb_adaptation_transports_anchor(self) -> None:
        from dngscan.scene_transform import SCENE_TRANSFORMS, _region_weight, wb_adaptation_ratios

        region = SCENE_TRANSFORMS["arri_skin_d55"].regions[0]
        ratios = wb_adaptation_ratios("camera", [1.484, 1.0, 2.328], [2.617, 1.312, 2.284])
        self.assertIsNotNone(ratios)
        r_r, r_b = ratios
        mu = region.mu_rg_bg
        # a pixel AT the transported anchor gets full weight under adaptation
        moved = dg.np.asarray([[mu[0] * r_r, 1.0, mu[1] * r_b]], dtype=dg.np.float32)
        w_adapt = float(_region_weight(moved, region, ratios)[0])
        self.assertGreater(w_adapt, 0.95)
        # while the ORIGINAL calibration anchor no longer peaks under adaptation
        original = dg.np.asarray([[mu[0], 1.0, mu[1]]], dtype=dg.np.float32)
        w_orig = float(_region_weight(original, region, ratios)[0])
        self.assertLess(w_orig, w_adapt)


if __name__ == "__main__":
    unittest.main()
