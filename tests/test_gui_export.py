# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for GUI export naming."""

from __future__ import annotations

import unittest

from dngscan.gui.service import export_suffix_parts


class ExportSuffixTests(unittest.TestCase):
    def test_default_agx_only(self) -> None:
        self.assertEqual(export_suffix_parts("clip", "srgb", "sdr"), "agx")

    def test_blender_reference_path_is_named(self) -> None:
        self.assertEqual(
            export_suffix_parts("clip", "srgb", "sdr", agx_primaries="base"),
            "agx_base",
        )
        self.assertEqual(
            export_suffix_parts("clip", "srgb", "sdr", tone_core="gated", agx_primaries="base"),
            "gated",
        )

    def test_includes_grade(self) -> None:
        self.assertEqual(
            export_suffix_parts("clip", "srgb", "sdr", "look:classic", 1.0),
            "agx_look_classic",
        )
        self.assertEqual(
            export_suffix_parts("clip", "srgb", "sdr", "filter:kodak_2383_d65", 1.0),
            "agx_filter_kodak_2383_d65",
        )

    def test_includes_grade_strength_when_not_one(self) -> None:
        self.assertEqual(
            export_suffix_parts("clip", "srgb", "sdr", "look:fuji_velvia", 0.8),
            "agx_look_fuji_velvia_gs0.8",
        )

    def test_includes_scene_transform(self) -> None:
        self.assertEqual(
            export_suffix_parts("clip", "p3", "sdr", "none", 1.0, "arri_skin_d55", 0.75),
            "agx_p3_arri_skin_d55_st0.75",
        )

    def test_neutral_export_suffix(self) -> None:
        self.assertEqual(
            export_suffix_parts("clip", "srgb", "sdr", tone_core="neutral"),
            "neutral",
        )
        self.assertEqual(
            export_suffix_parts("clip", "srgb", "sdr", tone_core="lum"),
            "lum",
        )
        self.assertEqual(
            export_suffix_parts("clip", "srgb", "sdr", tone_core="lum", lum_norm="power"),
            "lum_power",
        )


if __name__ == "__main__":
    unittest.main()
