#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Calibrate a demo Sigma fp -> ARRI-style scene-linear skin prefilter.

This is an offline tool: it writes a small JSON preset consumed by
`dngscan.scene_transform`.  Runtime JPEG export never imports this script and
does not need scipy/colour-science.

Data notes / replacement points:
- ALEV3 SSF: replace BUILTIN_ALEV3_SSF with digitized values from
  https://library.imaging.org/admin/apis/public/api/ist/website/downloadArticle/cic/23/1/art00029
- IMX410 QE: replace BUILTIN_IMX410_QE with a digitized ZWO ASI2400MC RGB QE
  curve.  That curve is a bare sensor/CFA proxy, not Sigma fp's final stack.
- Sigma fp hot mirror: demo uses a sigmoid red cutoff from DPReview user
  reports quoted in the handoff (lambda_c=660nm, width=15nm).  Replace with a
  measured transmission curve when available.
- Skin spectra: the built-in generator is only a low-dimensional demo skin
  manifold.  Pass --skin-csv for a real public skin reflectance data set.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

WL = np.arange(400.0, 701.0, 10.0, dtype=np.float64)


# Rough digitized-style curves on WL.  These are intentionally easy to replace:
# each row is R/G/B sensitivity, sampled at 400..700nm in 10nm increments.
BUILTIN_ALEV3_SSF = np.array(
    [
        [0.02, 0.03, 0.10, 0.22, 0.42, 0.62, 0.80, 0.89, 0.82, 0.62, 0.38, 0.18, 0.08, 0.04, 0.03, 0.04, 0.07, 0.14, 0.28, 0.48, 0.68, 0.82, 0.88, 0.84, 0.72, 0.54, 0.36, 0.22, 0.12, 0.06, 0.03],
        [0.02, 0.04, 0.08, 0.18, 0.36, 0.60, 0.82, 0.95, 1.00, 0.95, 0.86, 0.72, 0.54, 0.36, 0.22, 0.14, 0.09, 0.06, 0.04, 0.03, 0.025, 0.02, 0.016, 0.012, 0.010, 0.008, 0.006, 0.004, 0.003, 0.002, 0.001],
        [0.15, 0.34, 0.62, 0.86, 1.00, 0.94, 0.78, 0.56, 0.34, 0.18, 0.09, 0.045, 0.025, 0.016, 0.010, 0.008, 0.006, 0.005, 0.004, 0.003, 0.0025, 0.002, 0.0015, 0.001, 0.0008, 0.0006, 0.0005, 0.0004, 0.0003, 0.0002, 0.0001],
    ],
    dtype=np.float64,
).T

BUILTIN_IMX410_QE = np.array(
    [
        [0.01, 0.015, 0.03, 0.07, 0.14, 0.24, 0.38, 0.52, 0.62, 0.58, 0.44, 0.28, 0.16, 0.10, 0.12, 0.20, 0.34, 0.52, 0.70, 0.84, 0.92, 0.94, 0.90, 0.82, 0.70, 0.56, 0.42, 0.30, 0.20, 0.12, 0.06],
        [0.015, 0.025, 0.05, 0.11, 0.24, 0.44, 0.68, 0.86, 0.96, 1.00, 0.96, 0.82, 0.62, 0.40, 0.23, 0.13, 0.08, 0.05, 0.035, 0.025, 0.018, 0.014, 0.010, 0.008, 0.006, 0.0045, 0.0035, 0.0025, 0.0018, 0.0012, 0.0008],
        [0.08, 0.20, 0.42, 0.68, 0.88, 0.96, 1.00, 0.86, 0.62, 0.36, 0.18, 0.08, 0.035, 0.018, 0.011, 0.008, 0.006, 0.004, 0.003, 0.002, 0.0016, 0.0012, 0.0009, 0.0007, 0.0005, 0.0004, 0.0003, 0.0002, 0.00015, 0.0001, 0.00005],
    ],
    dtype=np.float64,
).T

XYZ_TO_REC2020 = np.array(
    [
        [1.7166511880, -0.3556707838, -0.2533662814],
        [-0.6666843518, 1.6164812366, 0.0157685458],
        [0.0176398574, -0.0427706133, 0.9421031212],
    ],
    dtype=np.float64,
)


def sigmoid_ir_cut(wavelengths: np.ndarray, cutoff_nm: float, width_nm: float) -> np.ndarray:
    red = 1.0 / (1.0 + np.exp((wavelengths - cutoff_nm) / max(width_nm, 1e-6)))
    blue = 1.0 / (1.0 + np.exp((420.0 - wavelengths) / 8.0))
    return red * blue


def blackbody_spd(wavelengths_nm: np.ndarray, temp_k: float) -> np.ndarray:
    wl_m = wavelengths_nm * 1e-9
    c2 = 1.438776877e-2
    spd = 1.0 / (np.power(wl_m, 5.0) * np.expm1(c2 / (wl_m * temp_k)))
    return spd / np.max(spd)


def illuminant_spd(name: str) -> np.ndarray:
    key = name.upper()
    if key == "A":
        return blackbody_spd(WL, 2856.0)
    if key == "D65":
        return blackbody_spd(WL, 6504.0)
    if key == "D55":
        return blackbody_spd(WL, 5500.0)
    raise ValueError(f"unknown illuminant: {name}")


def cie_1931_cmf_approx(wavelengths_nm: np.ndarray) -> np.ndarray:
    """Analytic CIE 1931 2-degree CMF approximation.

    This fallback keeps the demo self-contained.  Replace with colour-science
    tabulated CMFs if you need calibration-grade mask coordinates.
    """
    w = wavelengths_nm
    x_t1 = np.where(w < 442.0, (w - 442.0) * 0.0624, (w - 442.0) * 0.0374)
    x_t2 = np.where(w < 599.8, (w - 599.8) * 0.0264, (w - 599.8) * 0.0323)
    x_t3 = np.where(w < 501.1, (w - 501.1) * 0.0490, (w - 501.1) * 0.0382)
    x = 0.362 * np.exp(-0.5 * x_t1 * x_t1) + 1.056 * np.exp(-0.5 * x_t2 * x_t2) - 0.065 * np.exp(-0.5 * x_t3 * x_t3)

    y_t1 = np.where(w < 568.8, (w - 568.8) * 0.0213, (w - 568.8) * 0.0247)
    y_t2 = np.where(w < 530.9, (w - 530.9) * 0.0613, (w - 530.9) * 0.0322)
    y = 0.821 * np.exp(-0.5 * y_t1 * y_t1) + 0.286 * np.exp(-0.5 * y_t2 * y_t2)

    z_t1 = np.where(w < 437.0, (w - 437.0) * 0.0845, (w - 437.0) * 0.0278)
    z_t2 = np.where(w < 459.0, (w - 459.0) * 0.0385, (w - 459.0) * 0.0725)
    z = 1.217 * np.exp(-0.5 * z_t1 * z_t1) + 0.681 * np.exp(-0.5 * z_t2 * z_t2)
    return np.stack([x, y, z], axis=1)


def demo_skin_spectra() -> np.ndarray:
    spectra: list[np.ndarray] = []
    for melanin in np.linspace(0.0, 1.0, 8):
        for blood in np.linspace(0.4, 1.3, 6):
            for yellow in np.linspace(-0.03, 0.05, 3):
                base = 0.20 + 0.46 / (1.0 + np.exp(-(WL - 540.0) / 58.0))
                melanin_abs = (0.30 + 0.42 * melanin) * np.exp(-(WL - 400.0) / 155.0)
                hemo = blood * (
                    0.10 * np.exp(-0.5 * ((WL - 415.0) / 18.0) ** 2)
                    + 0.055 * np.exp(-0.5 * ((WL - 542.0) / 18.0) ** 2)
                    + 0.050 * np.exp(-0.5 * ((WL - 577.0) / 16.0) ** 2)
                )
                carotene = yellow * np.exp(-0.5 * ((WL - 590.0) / 75.0) ** 2)
                spectra.append(np.clip(base - melanin_abs - hemo + carotene, 0.025, 0.82))
    return np.asarray(spectra, dtype=np.float64)


def demo_cyan_spectra() -> np.ndarray:
    spectra: list[np.ndarray] = []
    for center in np.linspace(485.0, 520.0, 5):
        for width in np.linspace(34.0, 58.0, 4):
            blue_green = 0.04 + 0.55 * np.exp(-0.5 * ((WL - center) / width) ** 2)
            spectra.append(np.clip(blue_green + 0.05 / (1.0 + np.exp((WL - 610.0) / 28.0)), 0.02, 0.70))
    return np.asarray(spectra, dtype=np.float64)


def load_curve_csv(path: Path) -> np.ndarray:
    data = np.genfromtxt(path, delimiter=",", comments="#")
    if data.ndim != 2 or data.shape[1] < 4:
        raise ValueError(f"{path} must contain wavelength,R,G,B columns")
    order = np.argsort(data[:, 0])
    data = data[order]
    return np.stack([np.interp(WL, data[:, 0], data[:, i]) for i in (1, 2, 3)], axis=1)


def load_spectra_csv(path: Path) -> np.ndarray:
    data = np.genfromtxt(path, delimiter=",", comments="#")
    if data.ndim != 2:
        raise ValueError(f"{path} must be a 2D CSV")
    if data.shape[0] == WL.size + 1:
        wavelengths = data[1:, 0]
        return np.stack([np.interp(WL, wavelengths, data[1:, i]) for i in range(1, data.shape[1])], axis=0)
    if data.shape[1] == WL.size + 1:
        wavelengths = data[0, 1:]
        return np.stack([np.interp(WL, wavelengths, data[i, 1:]) for i in range(1, data.shape[0])], axis=0)
    if data.shape[1] == WL.size:
        return data.astype(np.float64, copy=False)
    raise ValueError(f"{path} must use 31 samples at 400..700nm or include wavelength headers")


def integrate_response(reflectance: np.ndarray, illuminant: np.ndarray, ssf: np.ndarray) -> np.ndarray:
    weighted = reflectance[:, :, None] * illuminant[None, :, None] * ssf[None, :, :]
    integrate = np.trapezoid if hasattr(np, "trapezoid") else np.trapz
    rgb = integrate(weighted, WL, axis=1)
    white = integrate(illuminant[:, None] * ssf, WL, axis=0)
    return rgb / np.maximum(white[None, :], 1e-12)


def spectra_to_rec2020(reflectance: np.ndarray, illuminant: np.ndarray) -> np.ndarray:
    cmf = cie_1931_cmf_approx(WL)
    xyz = integrate_response(reflectance, illuminant, cmf)
    rgb = xyz @ XYZ_TO_REC2020.T
    return np.clip(rgb, 1e-8, None)


def normalize_chroma(rgb: np.ndarray) -> np.ndarray:
    return rgb / np.maximum(rgb[:, 1:2], 1e-12)


def constrained_row_sum_fit(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    src_n = normalize_chroma(src)
    dst_n = normalize_chroma(dst)
    a = np.stack([src_n[:, 0] - src_n[:, 2], src_n[:, 1] - src_n[:, 2]], axis=1)
    matrix = np.empty((3, 3), dtype=np.float64)
    for row in range(3):
        b = dst_n[:, row] - src_n[:, 2]
        coeff, *_ = np.linalg.lstsq(a, b, rcond=None)
        matrix[row, 0] = coeff[0]
        matrix[row, 1] = coeff[1]
        matrix[row, 2] = 1.0 - coeff[0] - coeff[1]
    return matrix


def mask_params(src: np.ndarray, scale: float) -> tuple[list[float], list[list[float]]]:
    chroma = np.stack([src[:, 0] / np.maximum(src[:, 1], 1e-12), src[:, 2] / np.maximum(src[:, 1], 1e-12)], axis=1)
    mu = np.mean(chroma, axis=0)
    cov = np.cov(chroma.T)
    cov += np.eye(2) * 1e-5
    return [float(mu[0]), float(mu[1])], [[float(cov[0, 0]), float(cov[0, 1])], [float(cov[1, 0]), float(cov[1, 1])]]


def build_region(name: str, spectra: np.ndarray, illuminant: np.ndarray, fp_ssf: np.ndarray, alexa_ssf: np.ndarray, scale: float) -> dict:
    fp = integrate_response(spectra, illuminant, fp_ssf)
    alexa = integrate_response(spectra, illuminant, alexa_ssf)
    matrix = constrained_row_sum_fit(fp, alexa)
    mask_rgb = spectra_to_rec2020(spectra, illuminant)
    mu, cov = mask_params(mask_rgb, scale)
    return {
        "name": name,
        "matrix": [[round(float(v), 8) for v in row] for row in matrix],
        "mu_rg_bg": [round(v, 8) for v in mu],
        "cov_rg_bg": [[round(v, 10) for v in row] for row in cov],
        "scale": scale,
        "strength": 1.0,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Calibrate dngscan scene-transform skin/cyan preset.")
    parser.add_argument("--out", type=Path, default=Path("dngscan/scene_transform_presets.json"))
    parser.add_argument("--illuminant", choices=("D55", "D65", "A"), default="D55")
    parser.add_argument("--ir-cutoff", type=float, default=660.0)
    parser.add_argument("--ir-width", type=float, default=15.0)
    parser.add_argument("--mask-scale", type=float, default=2.5)
    parser.add_argument("--alexa-ssf-csv", type=Path)
    parser.add_argument("--imx410-qe-csv", type=Path)
    parser.add_argument("--skin-csv", type=Path)
    parser.add_argument("--cyan-csv", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    alexa_ssf = load_curve_csv(args.alexa_ssf_csv) if args.alexa_ssf_csv else BUILTIN_ALEV3_SSF
    imx410_qe = load_curve_csv(args.imx410_qe_csv) if args.imx410_qe_csv else BUILTIN_IMX410_QE
    transmission = sigmoid_ir_cut(WL, args.ir_cutoff, args.ir_width)
    fp_ssf = imx410_qe * transmission[:, None]
    illum = illuminant_spd(args.illuminant)
    skin = load_spectra_csv(args.skin_csv) if args.skin_csv else demo_skin_spectra()
    cyan = load_spectra_csv(args.cyan_csv) if args.cyan_csv else demo_cyan_spectra()

    key = f"arri_skin_{args.illuminant.lower()}"
    payload = {
        "version": 1,
        "transforms": {
            key: {
                "name": key,
                "label": f"ARRI skin prefeed ({args.illuminant})",
                "illuminant": args.illuminant,
                "working_space": "Rec2020",
                "note": (
                    "Demo spectral fit from rough ALEV3/IMX410 curves and a sigmoid Sigma fp hot-mirror model; "
                    "replace curves with measured CSV data for production calibration."
                ),
                "regions": [
                    build_region("skin", skin, illum, fp_ssf, alexa_ssf, args.mask_scale),
                    build_region("cyan", cyan, illum, fp_ssf, alexa_ssf, args.mask_scale),
                ],
            }
        },
        "sources": {
            "alev3_ssf": "CIC 23 paper, modelled ARRI ALEXA SSF; rough built-in values are placeholders.",
            "imx410_qe": "ZWO ASI2400MC / Sony IMX410 RGB QE curve; rough built-in values are placeholders.",
            "sigma_fp_hot_mirror": f"sigmoid transmission with red cutoff {args.ir_cutoff:g}nm, width {args.ir_width:g}nm.",
            "skin_spectra": "Built-in analytic demo skin manifold unless --skin-csv is provided.",
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
