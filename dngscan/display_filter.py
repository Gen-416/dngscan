# SPDX-License-Identifier: GPL-3.0-or-later
"""Full display LUT filters (log encode -> .cube -> display).

Unlike dngscan.look (chromatic geometry only, L untouched), these are output
transforms: Kodak 2383 FPE (Cineon log in) and RED IPP2 (Log3G10/RWG in).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._deps import np
from .color import apply_rgb_matrix3, rec2020_to_output, rec2020_to_srgb, rec2020_to_xyz, srgb_to_output
from .log_encode import XYZ_TO_RWG, encode_for_source
from .lut_io import get_cube, sample_cube

_ASSETS = Path(__file__).resolve().parents[1] / "dngscan_assets" / "vendor_luts"


@dataclass(frozen=True)
class DisplayFilter:
    label: str
    cube: Path
    source: str  # cineon | log3g10
    input_space: str  # rec709 | rwg — linear RGB space fed to the encoder
    display_gamma: float  # pow on LUT output to reach scene-linear Rec.709 (1.0 = already linear)


DISPLAY_FILTERS: dict[str, DisplayFilter] = {
    "kodak_2383_d65": DisplayFilter(
        label="Kodak 2383 D65 (Resolve FPE)",
        cube=_ASSETS / "resolve_film_looks" / "Rec709 Kodak 2383 D65.cube",
        source="cineon",
        input_space="rec709",
        display_gamma=2.4,
    ),
    "red_ipp2_rec709_medium": DisplayFilter(
        label="RED IPP2 Rec709 Medium",
        cube=_ASSETS
        / "red_ipp2"
        / "REC709"
        / "RWG_Log3G10 to REC709_BT1886 with MEDIUM_CONTRAST and R_2_Medium size_33 v1.13.cube",
        source="log3g10",
        input_space="rwg",
        display_gamma=2.4,
    ),
}

FILTER_CHOICES: tuple[str, ...] = ("none",) + tuple(DISPLAY_FILTERS)


def filter_available(name: str) -> bool:
    if name == "none":
        return True
    spec = DISPLAY_FILTERS.get(name)
    return spec is not None and spec.cube.is_file()


def _linear_to_encoder_input(rec2020_linear: np.ndarray, spec: DisplayFilter) -> np.ndarray:
    if spec.input_space == "rec709":
        return rec2020_to_srgb(rec2020_linear)
    if spec.input_space == "rwg":
        xyz = rec2020_to_xyz(rec2020_linear)
        return apply_rgb_matrix3(xyz, XYZ_TO_RWG)
    raise ValueError(f"unknown input_space: {spec.input_space}")


def apply_display_filter_rec2020(
    mapped_rec2020: Any,
    output_gamut: str,
    filter_name: str,
    strength: float = 1.0,
) -> Any:
    """Blend AgX Rec.2020 display with a log-encoded display LUT."""
    if filter_name == "none" or strength <= 0.0:
        flat = mapped_rec2020.reshape(-1, 3)
        return rec2020_to_output(flat, output_gamut).reshape(mapped_rec2020.shape)

    if filter_name not in DISPLAY_FILTERS:
        raise ValueError(f"unknown display filter: {filter_name}")
    spec = DISPLAY_FILTERS[filter_name]
    if not spec.cube.is_file():
        raise FileNotFoundError(f"缺少 display LUT：{spec.cube}")

    lut = get_cube(spec.cube)
    flat = mapped_rec2020.reshape(-1, 3).astype(np.float32, copy=False)
    agx_display = rec2020_to_output(flat, output_gamut)

    encoder_in = _linear_to_encoder_input(flat, spec)
    encoded = encode_for_source(encoder_in, spec.source)
    lut_out = sample_cube(lut, encoded)
    if spec.display_gamma > 1.0 + 1e-6:
        display_709 = np.power(np.clip(lut_out, 0.0, 1.0), spec.display_gamma)
    else:
        display_709 = np.clip(lut_out, 0.0, 1.0)
    filtered = srgb_to_output(display_709, output_gamut)

    s = np.float32(min(1.5, max(0.0, strength)))
    out = agx_display * (np.float32(1.0) - s) + filtered * s
    return out.reshape(mapped_rec2020.shape).astype(np.float32, copy=False)
