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


if __name__ == "__main__":
    unittest.main()
