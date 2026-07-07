# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import unittest

from dngscan._deps import np
from dngscan.raw_io import build_clip_masks


def test_build_clip_masks_uses_cfa_max_binning():
    raw = np.full((4, 4), 100, dtype=np.uint16)
    colors = np.asarray(
        [
            [0, 1, 0, 1],
            [3, 2, 3, 2],
            [0, 1, 0, 1],
            [3, 2, 3, 2],
        ],
        dtype=np.uint8,
    )
    raw[0, 0] = 990
    raw[1, 1] = 970
    masks = build_clip_masks(
        raw,
        colors,
        "RGBG",
        white_level=1000,
        black_levels=[0.0, 0.0, 0.0, 0.0],
        camera_white_levels=[1000.0, 1000.0, 1000.0, 1000.0],
        orientation_flip=0,
        scene_shape=(2, 2),
    ).astype(np.float32)
    assert masks.shape == (2, 2, 3)
    assert float(masks[0, 0, 0]) > 0.2
    assert float(masks[0, 0, 2]) > 0.05
    assert float(masks[1, 1, 0]) < float(masks[0, 0, 0])


class RawClipMasksTest(unittest.TestCase):
    test_build_clip_masks_uses_cfa_max_binning = staticmethod(test_build_clip_masks_uses_cfa_max_binning)


if __name__ == "__main__":
    unittest.main()
