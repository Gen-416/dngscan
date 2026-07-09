# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import unittest

import numpy as np

from dngscan.guidance import (
    CLIP_CLASS_G,
    CLIP_CLASS_NONE,
    CLIP_CLASS_RGB,
    build_raw_guidance_maps,
    clip_class_from_masks,
    color_path_weight,
    raw_color_permission,
    sector_hue_multiplier,
    snr_confidence_from_ev,
)


class GuidanceTest(unittest.TestCase):
    def test_clip_class_discrete(self) -> None:
        masks = np.asarray([[0.0, 0.0, 0.0], [0.0, 0.5, 0.0], [0.6, 0.6, 0.6]], dtype=np.float32)
        classes = clip_class_from_masks(masks)
        self.assertEqual(int(classes[0]), CLIP_CLASS_NONE)
        self.assertEqual(int(classes[1]), CLIP_CLASS_G)
        self.assertEqual(int(classes[2]), CLIP_CLASS_RGB)

    def test_unclipped_midtone_low_permission(self) -> None:
        masks = np.asarray([[0.0, 0.0, 0.0]], dtype=np.float32)
        ev = np.asarray([-1.0], dtype=np.float32)
        self.assertLess(float(raw_color_permission(masks)[0]), 0.05)
        self.assertLess(float(color_path_weight(masks, ev)[0]), 0.08)

    def test_rgb_clip_high_permission(self) -> None:
        masks = np.asarray([[0.9, 0.85, 0.95]], dtype=np.float32)
        ev = np.asarray([2.5], dtype=np.float32)
        self.assertGreater(float(color_path_weight(masks, ev)[0]), 0.5)

    def test_skin_midtone_sector_reduces_weight(self) -> None:
        skin = sector_hue_multiplier(
            np.asarray([[0.42, 0.22, 0.18]], dtype=np.float32),
            np.asarray([0.0], dtype=np.float32),
        )
        neutral = sector_hue_multiplier(
            np.asarray([[0.22, 0.22, 0.22]], dtype=np.float32),
            np.asarray([0.0], dtype=np.float32),
        )
        self.assertLess(float(skin[0]), float(neutral[0]))

    def test_snr_confidence_rises_with_ev(self) -> None:
        low = float(snr_confidence_from_ev(np.asarray([-10.0]), -12.0)[0])
        high = float(snr_confidence_from_ev(np.asarray([0.0]), -12.0)[0])
        self.assertLess(low, high)


if __name__ == "__main__":
    unittest.main()
