# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import unittest

from dngscan._deps import np
from dngscan.color import rgb_to_oklab
from dngscan.render import _apply_display_highlight_chroma_retreat


class DisplayHighlightChromaRetreatTest(unittest.TestCase):
    def test_black_and_midtones_are_unchanged(self) -> None:
        rgb = np.asarray([[0.02, 0.01, 0.005], [0.22, 0.08, 0.03]], dtype=np.float32)
        out = _apply_display_highlight_chroma_retreat(rgb, "p3", 0.35)
        self.assertTrue(np.allclose(out, rgb, atol=1e-6))

    def test_near_white_chroma_recedes_without_lightness_shift(self) -> None:
        rgb = np.asarray([[1.0, 0.68, 0.22]], dtype=np.float32)
        out = _apply_display_highlight_chroma_retreat(rgb, "p3", 0.35)
        before = rgb_to_oklab(rgb, "p3")
        after = rgb_to_oklab(out, "p3")
        self.assertAlmostEqual(float(before[0][0]), float(after[0][0]), places=5)
        self.assertLess(float(np.hypot(after[1][0], after[2][0])), float(np.hypot(before[1][0], before[2][0])))


if __name__ == "__main__":
    unittest.main()
