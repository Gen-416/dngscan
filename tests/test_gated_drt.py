# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import unittest

import numpy as np

from dngscan.color import rgb_to_oklab
from dngscan.gated_drt import apply_gated_core
from dngscan.models import ColorGeometryPlan, ToneCompressionPlan


def _plan(tone_core: str = "gated", primaries: str = "smooth") -> ToneCompressionPlan:
    return ToneCompressionPlan(
        target_gamut="Rec2020",
        luma_p1=0.01,
        luma_p50=0.18,
        luma_p99=1.0,
        luma_p999=2.0,
        black_ev=-7.0,
        white_ev=4.5,
        dynamic_range_ev=11.5,
        contrast=3.0,
        toe_power=1.5,
        shoulder_power=3.3,
        chroma_p95=0.0,
        negative_rgb_pct=0.0,
        over_rgb_pct=0.0,
        tone_core=tone_core,
        agx_primaries=primaries,
        use_c1_endpoints=True,
    )


class GatedDrtTest(unittest.TestCase):
    def test_midtone_preserves_more_chroma_than_full_agx(self) -> None:
        from dngscan.render import apply_agx_core

        rgb = np.asarray([[0.28, 0.10, 0.22]], dtype=np.float32)
        plan = _plan()
        color = ColorGeometryPlan(
            target_gamut="srgb",
            raw_clip_retreat_strength=0.0,
            output_gamut_pressure_pct=0.0,
        )
        clean_masks = np.zeros((1, 3), dtype=np.float32)
        gated = apply_gated_core(rgb, plan, color, clean_masks)
        full = apply_agx_core(rgb, _plan(tone_core="agx", primaries="base"))

        def chroma(v):
            lab = rgb_to_oklab(v, "srgb")
            return float(np.hypot(lab[1][0], lab[2][0]))

        self.assertGreater(chroma(gated), chroma(full))

    def test_clipped_highlight_moves_toward_agx(self) -> None:
        rgb = np.asarray([[0.85, 0.75, 0.20]], dtype=np.float32)
        plan = _plan()
        color = ColorGeometryPlan(
            target_gamut="srgb",
            raw_clip_retreat_strength=0.0,
            output_gamut_pressure_pct=0.0,
        )
        clean = apply_gated_core(rgb, plan, color, np.zeros((1, 3), dtype=np.float32))
        clipped = apply_gated_core(rgb, plan, color, np.asarray([[0.95, 0.1, 0.1]], dtype=np.float32))
        self.assertGreater(float(np.abs(clipped - clean).max()), 1e-3)


if __name__ == "__main__":
    unittest.main()
