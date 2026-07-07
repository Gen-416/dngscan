# SPDX-License-Identifier: GPL-3.0-or-later
"""Camera / print log encoders for display LUT filters (not ARRI look measurement)."""
from __future__ import annotations

from typing import Any

from ._deps import np

_RWG_TO_XYZ = np.array(
    [
        [0.735275, 0.068609, 0.146571],
        [0.286694, 0.842979, -0.129673],
        [-0.079682, -0.347343, 1.516745],
    ],
    dtype=np.float64,
)
RWG_TO_XYZ = _RWG_TO_XYZ
XYZ_TO_RWG = np.linalg.inv(_RWG_TO_XYZ)

# RED Log3G10 (IPP2 white paper 915-0187): 18% -> 1/3, 10 stops above -> 1.0
_LOG3G10_A = 0.224282
_LOG3G10_B = 155.975327
_LOG3G10_C = 0.01
_LOG3G10_G = 15.1927
LOG3G10_MIDGRAY = 1.0 / 3.0


def cineon_encode(x: np.ndarray) -> np.ndarray:
    """Canonical Cineon Film Log: code = (685 + 300*log10(x)) / 1023.

    This is the encoding Resolve's Film Look (PFE) LUTs are authored against:
    18% gray -> 0.4512, diffuse white 1.0 -> 0.6696 (the print-stock shoulder lives
    in the codes above that). Anchoring mid gray at 0.5 instead rides ~1/3 stop too
    high up the print curve and never reaches the 2383 highlight density."""
    x = np.maximum(x, 1e-10)
    return np.clip((685.0 + 300.0 * np.log10(x)) / 1023.0, 0.0, 1.0)


def log3g10_encode(x: np.ndarray) -> np.ndarray:
    """RED Log3G10 (IPP2): scene-linear RWG in, float log code out (18% -> 1/3)."""
    x = np.asarray(x, dtype=np.float64) + _LOG3G10_C
    lo = x * _LOG3G10_G
    hi = _LOG3G10_A * np.log10(np.maximum(x * _LOG3G10_B + 1.0, 1e-10))
    return np.where(x < 0.0, lo, hi).astype(np.float32)


def encode_for_source(rgb_linear: np.ndarray, source: str) -> np.ndarray:
    if source == "cineon":
        return cineon_encode(rgb_linear)
    if source == "log3g10":
        return log3g10_encode(rgb_linear)
    raise ValueError(f"unknown log source: {source}")
