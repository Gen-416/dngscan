# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for the ARRI-geometry look layer (no LUT files required)."""

from __future__ import annotations

import unittest

import numpy as np

from dngscan.look import LOOK_FIELDS, apply_look_oklab


class LookLayerTests(unittest.TestCase):
    def test_strength_zero_is_identity(self) -> None:
        L = np.array([0.2, 0.5, 0.8], dtype=np.float32)
        a = np.array([0.08, 0.12, 0.05], dtype=np.float32)
        b = np.array([0.04, -0.06, 0.10], dtype=np.float32)
        for look in ("classic", "reveal"):
            L2, a2, b2 = apply_look_oklab(L, a, b, look, strength=0.0)
            np.testing.assert_allclose(L2, L, rtol=0, atol=1e-6)
            np.testing.assert_allclose(a2, a, rtol=0, atol=1e-6)
            np.testing.assert_allclose(b2, b, rtol=0, atol=1e-6)

    def test_luminance_unchanged(self) -> None:
        L = np.linspace(0.15, 0.85, 64, dtype=np.float32)
        a = np.full_like(L, 0.10)
        b = np.full_like(L, 0.05)
        for look in ("classic", "reveal"):
            L2, _, _ = apply_look_oklab(L, a, b, look, strength=1.0)
            np.testing.assert_allclose(L2, L, rtol=0, atol=1e-7)

    def test_classic_differs_from_reveal_on_green(self) -> None:
        # Oklab hue ~120° (green sector); classic vs reveal diverge on hue rotation.
        L = np.array([0.55], dtype=np.float32)
        hue_deg = 120.0
        c = 0.12
        rad = np.radians(hue_deg)
        a = np.array([c * np.cos(rad)], dtype=np.float32)
        b = np.array([c * np.sin(rad)], dtype=np.float32)
        _, ac, bc = apply_look_oklab(L, a, b, "classic", 1.0)
        _, ar, br = apply_look_oklab(L, a, b, "reveal", 1.0)
        self.assertGreater(abs(ac.item() - ar.item()) + abs(bc.item() - br.item()), 1e-4)

    def test_reduces_chroma_at_mid_l(self) -> None:
        L = np.array([0.55], dtype=np.float32)
        a = np.array([0.14], dtype=np.float32)
        b = np.array([0.02], dtype=np.float32)
        c_in = float(np.hypot(a.item(), b.item()))
        _, a2, b2 = apply_look_oklab(L, a, b, "classic", 1.0)
        c_out = float(np.hypot(a2.item(), b2.item()))
        self.assertLess(c_out, c_in * LOOK_FIELDS["classic"].mid_chroma_ratio + 0.02)

    def test_green_sector_rotates_toward_cyan(self) -> None:
        # Measured classic yellow-green sector (30-60°) has negative Δhue (toward cyan).
        field = LOOK_FIELDS["classic"]
        self.assertLess(field.hue_rotation_deg[1], 0.0)
        L = np.array([0.55], dtype=np.float32)
        hue_deg = 45.0
        c = 0.10
        rad = np.radians(hue_deg)
        a = np.array([c * np.cos(rad)], dtype=np.float32)
        b = np.array([c * np.sin(rad)], dtype=np.float32)
        _, a2, b2 = apply_look_oklab(L, a, b, "classic", 1.0)
        h_out = float(np.degrees(np.arctan2(b2.item(), a2.item())) % 360.0)
        delta = (h_out - hue_deg + 180.0) % 360.0 - 180.0
        self.assertLess(delta, -0.5)


if __name__ == "__main__":
    unittest.main()
