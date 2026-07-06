# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for display LUT filters (log encode -> .cube)."""

from __future__ import annotations

import unittest

import numpy as np

from dngscan.color import rec2020_to_output
from dngscan.display_filter import (
    DISPLAY_FILTERS,
    apply_display_filter_rec2020,
    filter_available,
)
from dngscan.log_encode import cineon_encode, log3g10_encode


class DisplayFilterTests(unittest.TestCase):
    def test_cineon_anchor(self) -> None:
        got = float(cineon_encode(np.array([0.18]))[0])
        self.assertAlmostEqual(got, 0.5, places=3)

    def test_log3g10_midgray(self) -> None:
        from dngscan.log_encode import LOG3G10_MIDGRAY

        got = float(log3g10_encode(np.array([0.18]))[0])
        self.assertAlmostEqual(got, LOG3G10_MIDGRAY, places=3)

    def test_filter_none_matches_agx_display(self) -> None:
        rec = np.array([[[0.4, 0.35, 0.3]]], dtype=np.float32)
        flat = rec.reshape(-1, 3)
        expected = rec2020_to_output(flat, "srgb").reshape(rec.shape)
        out = apply_display_filter_rec2020(rec, "srgb", "none", 1.0)
        np.testing.assert_allclose(out, expected, rtol=0, atol=1e-6)

    def test_filter_strength_zero_matches_agx_display(self) -> None:
        rec = np.array([[[0.4, 0.35, 0.3]]], dtype=np.float32)
        flat = rec.reshape(-1, 3)
        expected = rec2020_to_output(flat, "srgb").reshape(rec.shape)
        out = apply_display_filter_rec2020(rec, "srgb", "kodak_2383_d65", 0.0)
        np.testing.assert_allclose(out, expected, rtol=0, atol=1e-6)

    def test_vendor_cubes_present(self) -> None:
        for name in ("kodak_2383_d65", "red_ipp2_rec709_medium"):
            self.assertTrue(filter_available(name), msg=name)
            self.assertTrue(DISPLAY_FILTERS[name].cube.is_file(), msg=name)

    def test_kodak_filter_preserves_color(self) -> None:
        if not filter_available("kodak_2383_d65"):
            self.skipTest("Kodak cube missing")
        # Mid-gray with strong green bias in Rec.2020 linear
        rec = np.array([[[0.18, 0.22, 0.14]]], dtype=np.float32)
        out = apply_display_filter_rec2020(rec, "srgb", "kodak_2383_d65", 1.0)
        spread = float(np.max(out) - np.min(out))
        self.assertGreater(spread, 0.02, "filter output should not be near grayscale")

    def test_red_filter_preserves_color(self) -> None:
        if not filter_available("red_ipp2_rec709_medium"):
            self.skipTest("RED IPP2 cube missing")
        rec = np.array([[[0.18, 0.22, 0.14]]], dtype=np.float32)
        out = apply_display_filter_rec2020(rec, "srgb", "red_ipp2_rec709_medium", 1.0)
        spread = float(np.max(out) - np.min(out))
        self.assertGreater(spread, 0.05, "filter output should not be near grayscale")

    def test_log3g10_monotonic(self) -> None:
        x = np.linspace(0.0, 1.0, 32, dtype=np.float64)
        y = log3g10_encode(x)
        self.assertTrue(np.all(np.diff(y) >= -1e-6))


if __name__ == "__main__":
    unittest.main()
