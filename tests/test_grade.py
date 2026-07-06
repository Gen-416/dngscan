# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for unified grade selection."""

from __future__ import annotations

import unittest

from dngscan.grade import resolve_grade, resolve_grade_params


class GradeTests(unittest.TestCase):
    def test_mutually_exclusive_legacy_params(self) -> None:
        with self.assertRaises(ValueError):
            resolve_grade_params({"look": "classic", "filter": "kodak_2383_d65"})

    def test_filter_grade(self) -> None:
        look, ls, filt, fs = resolve_grade("kodak_2383_d65", 0.8)
        self.assertEqual(look, "none")
        self.assertEqual(filt, "kodak_2383_d65")
        self.assertAlmostEqual(fs, 0.8)

    def test_look_grade(self) -> None:
        look, ls, filt, fs = resolve_grade("classic", 1.0)
        self.assertEqual(look, "classic")
        self.assertEqual(filt, "none")


if __name__ == "__main__":
    unittest.main()
