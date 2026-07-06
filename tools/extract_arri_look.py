# SPDX-License-Identifier: GPL-3.0-or-later
"""Measure the chromatic geometry of ARRI's official display LUTs against dngscan's AgX.

Offline analysis harness: feeds a synthetic scene-linear sweep (hue ring × L ladder ×
saturation gradient) through (a) an official ARRI LogC->Rec.709 .cube (user-downloaded,
NOT part of this repo) and (b) dngscan's AgX render, then compares both in Oklab.
The measured delta fields parameterize dngscan.look.LookField — geometry only, no LUT data.

Usage (from repo root, with the project venv):
    python tools/extract_arri_look.py
    python tools/extract_arri_look.py --emit python   # print LOOK_FIELDS snippet
    python tools/extract_arri_look.py --emit json --out look_fields.json
    python tools/extract_arri_look.py --validate      # fit error vs ARRI after look apply
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dngscan.core as dg  # noqa: E402
from dngscan import agx as agx_engine  # noqa: E402
from dngscan.look import LookField, apply_look_oklab  # noqa: E402

ASSETS = Path(__file__).resolve().parents[1] / "dngscan_assets" / "arri"
LUTS = {
    "classic": ("K1S1 (Classic 709, LogC3)", "ARRI_LogC3-to-Gamma24_Rec709_D65-Classic_33.cube", "logc3"),
    "reveal": ("Reveal (ARRI 709 v1, LogC4)", "ARRI_LogC4-to-Gamma24_Rec709-D65_v1_65.cube", "logc4"),
}

SKIN_HUE_LO = 20.0
SKIN_HUE_HI = 60.0
SKIN_HUE_CENTER = 40.0


def logc3_encode(x: np.ndarray) -> np.ndarray:
    cut, a, b, c, d, e, f = 0.010591, 5.555556, 0.052272, 0.247190, 0.385537, 5.367655, 0.092809
    return np.where(x > cut, c * np.log10(a * x + b) + d, e * x + f)


_LC4_A = (2.0**18 - 16.0) / 117.45
_LC4_B = (1023.0 - 95.0) / 1023.0
_LC4_C = 95.0 / 1023.0
_LC4_S = (7.0 * math.log(2.0) * 2.0 ** (7.0 - 14.0 * _LC4_C / _LC4_B)) / (_LC4_A * _LC4_B)
_LC4_T = (2.0 ** (14.0 * (-_LC4_C / _LC4_B) + 6.0) - 64.0) / _LC4_A


def logc4_encode(x: np.ndarray) -> np.ndarray:
    return np.where(
        x < _LC4_T,
        (x - _LC4_T) / _LC4_S,
        (np.log2(_LC4_A * x + 64.0) - 6.0) / 14.0 * _LC4_B + _LC4_C,
    )


AWG3_TO_XYZ = np.array(
    [
        [0.638008, 0.214704, 0.097744],
        [0.291954, 0.823841, -0.115795],
        [0.002798, -0.067034, 1.153294],
    ]
)
AWG4_TO_XYZ = np.array(
    [
        [0.704858320407232, 0.129760295170463, 0.115837311473977],
        [0.254524176404027, 0.781477732712002, -0.036001909116029],
        [0.0, 0.0, 1.089057750759878],
    ]
)
XYZ_TO_AWG3 = np.linalg.inv(AWG3_TO_XYZ)
XYZ_TO_AWG4 = np.linalg.inv(AWG4_TO_XYZ)


class TypicalPlan:
    black_ev, white_ev, contrast, toe_power, shoulder_power = -6.55, 3.05, 2.99, 1.38, 3.28


def load_cube(path: Path) -> np.ndarray:
    size = None
    rows: list[list[float]] = []
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("TITLE"):
                continue
            if line.startswith("LUT_3D_SIZE"):
                size = int(line.split()[1])
                continue
            if line.startswith(("DOMAIN_MIN", "DOMAIN_MAX", "LUT_1D")):
                continue
            parts = line.split()
            if len(parts) == 3:
                rows.append([float(v) for v in parts])
    if size is None or len(rows) != size**3:
        raise RuntimeError(f"bad cube {path}: size={size} rows={len(rows)}")
    return np.asarray(rows, dtype=np.float64).reshape(size, size, size, 3).transpose(2, 1, 0, 3)


def sample_cube(lut: np.ndarray, rgb01: np.ndarray) -> np.ndarray:
    n = lut.shape[0]
    coords = np.clip(rgb01, 0.0, 1.0) * (n - 1)
    lo = np.floor(coords).astype(int)
    hi = np.minimum(lo + 1, n - 1)
    frac = coords - lo
    out = np.zeros_like(rgb01)
    for corner in range(8):
        ix = hi[:, 0] if corner & 1 else lo[:, 0]
        iy = hi[:, 1] if corner & 2 else lo[:, 1]
        iz = hi[:, 2] if corner & 4 else lo[:, 2]
        wx = frac[:, 0] if corner & 1 else 1.0 - frac[:, 0]
        wy = frac[:, 1] if corner & 2 else 1.0 - frac[:, 1]
        wz = frac[:, 2] if corner & 4 else 1.0 - frac[:, 2]
        out += lut[ix, iy, iz] * (wx * wy * wz)[:, None]
    return out


def xyz_to_oklab(xyz: np.ndarray) -> np.ndarray:
    lms = xyz @ np.asarray(dg.OKLAB_M1).T
    return np.cbrt(np.maximum(lms, 0.0)) @ np.asarray(dg.OKLAB_M2).T


def hsv_to_linear_rgb(h_deg: float, s: float) -> np.ndarray:
    import colorsys

    return np.array(colorsys.hsv_to_rgb(h_deg / 360.0, s, 1.0))


def build_scene_sweep() -> np.ndarray:
    samples: list[np.ndarray] = []
    for k in range(-5, 4):
        v = 0.18 * 2.0**k
        samples.append(np.array([v, v, v]))
        for h in range(0, 360, 10):
            for s in (0.15, 0.25, 0.5, 0.75, 1.0):
                samples.append(hsv_to_linear_rgb(h, s) * v)
    return np.asarray(samples)


def render_agx_oklab(scene_xyz: np.ndarray) -> np.ndarray:
    scene_2020 = scene_xyz @ np.asarray(dg.XYZ_TO_RGB["Rec2020"]).T
    agx_2020 = agx_engine.apply_core(
        scene_2020.astype(np.float32), TypicalPlan, agx_engine.AGX_INSET_REC2020, agx_engine.AGX_OUTSET_REC2020
    ).astype(np.float64)
    agx_xyz = agx_2020 @ np.asarray(dg.RGB_TO_XYZ["Rec2020"]).T
    return xyz_to_oklab(agx_xyz)


def render_arri_oklab(scene_xyz: np.ndarray, lut_path: Path, enc: str) -> np.ndarray:
    lut = load_cube(lut_path)
    if enc == "logc3":
        cam = scene_xyz @ XYZ_TO_AWG3.T
        encoded = logc3_encode(np.maximum(cam, 0.0))
    else:
        cam = scene_xyz @ XYZ_TO_AWG4.T
        encoded = logc4_encode(cam)
    disp = sample_cube(lut, np.clip(encoded, 0.0, 1.0))
    disp_lin = np.power(np.clip(disp, 0.0, 1.0), 2.4)
    arri_xyz = disp_lin @ np.asarray(dg.RGB_TO_XYZ["sRGB"]).T
    return xyz_to_oklab(arri_xyz)


def _median_or(default: float, values: np.ndarray) -> float:
    if values.size == 0:
        return default
    return float(np.median(values))


def _fit_shadow_l_hi(L_a: np.ndarray, cr: np.ndarray, shadow_ratio: float, mid_ratio: float) -> float:
    target = 0.5 * (shadow_ratio + mid_ratio)
    bins = np.linspace(0.08, 0.45, 10)
    for lo, hi in zip(bins[:-1], bins[1:]):
        m = (L_a >= lo) & (L_a < hi)
        if np.count_nonzero(m) >= 8 and _median_or(mid_ratio, cr[m]) >= target:
            return float(hi)
    return 0.35


def measure_look_field(lab_a: np.ndarray, lab_r: np.ndarray) -> LookField:
    L_a = lab_a[:, 0]
    C_a = np.hypot(lab_a[:, 1], lab_a[:, 2])
    h_a = np.degrees(np.arctan2(lab_a[:, 2], lab_a[:, 1])) % 360.0
    L_r = lab_r[:, 0]
    C_r = np.hypot(lab_r[:, 1], lab_r[:, 2])
    h_r = np.degrees(np.arctan2(lab_r[:, 2], lab_r[:, 1])) % 360.0
    dh = (h_r - h_a + 180.0) % 360.0 - 180.0
    cr = C_r / np.maximum(C_a, 1e-5)

    mid = (L_a > 0.35) & (L_a < 0.75) & (C_a > 0.05) & (C_a < 0.20)
    hue_rot: list[float] = []
    chroma_sector: list[float] = []
    for lo in range(0, 360, 30):
        m = mid & (h_a >= lo) & (h_a < lo + 30)
        hue_rot.append(_median_or(0.0, dh[m]))
        chroma_sector.append(_median_or(1.0, cr[m]))

    mid_chroma = _median_or(1.0, cr[mid])
    shad = (L_a > 0.08) & (L_a < 0.35)
    shad_c = shad & (C_a > 0.04)
    shad_n = shad & (C_a < 0.02) & (C_a > 0.002)
    shadow_chroma = _median_or(mid_chroma, cr[shad_c])
    hi = (L_a > 0.80) & (C_a > 0.03)
    highlight_chroma = _median_or(mid_chroma, cr[hi])
    high_c = mid & (C_a > 0.16)
    high_chroma = _median_or(mid_chroma, cr[(L_a > 0.35) & (L_a < 0.75) & (C_a > 0.20)])

    sat_knee_c = _median_or(0.17, C_a[(L_a > 0.35) & (L_a < 0.75) & (C_a > 0.14)])
    sat_knee_relief = high_chroma / max(mid_chroma, 1e-5)

    skin = (h_a >= SKIN_HUE_LO) & (h_a <= SKIN_HUE_HI) & mid
    skin_chroma_scale = _median_or(mid_chroma, cr[skin]) / max(mid_chroma, 1e-5)
    std_in = float(np.std(h_a[skin])) if np.count_nonzero(skin) >= 6 else 0.0
    std_out = float(np.std(h_r[skin])) if np.count_nonzero(skin) >= 6 else std_in
    skin_hue_pull = max(0.0, 1.0 - std_out / std_in) if std_in > 1e-3 else 0.0

    shadow_l_hi = _fit_shadow_l_hi(L_a, cr, shadow_chroma, mid_chroma)

    return LookField(
        hue_rotation_deg=tuple(round(v, 2) for v in hue_rot),
        chroma_ratio=tuple(round(v, 3) for v in chroma_sector),
        mid_chroma_ratio=round(mid_chroma, 3),
        shadow_chroma_ratio=round(shadow_chroma, 3),
        highlight_chroma_ratio=round(highlight_chroma, 3),
        shadow_cool_a=round(_median_or(0.0, (lab_r[shad_n, 1] - lab_a[shad_n, 1])), 4) if np.count_nonzero(shad_n) >= 4 else 0.0,
        shadow_cool_b=round(_median_or(0.0, (lab_r[shad_n, 2] - lab_a[shad_n, 2])), 4) if np.count_nonzero(shad_n) >= 4 else 0.0,
        shadow_l_lo=0.10,
        shadow_l_hi=round(shadow_l_hi, 2),
        highlight_l_lo=0.75,
        highlight_l_hi=0.92,
        sat_knee_c=round(sat_knee_c, 2),
        sat_knee_relief=round(sat_knee_relief, 3),
        skin_hue_lo=SKIN_HUE_LO,
        skin_hue_hi=SKIN_HUE_HI,
        skin_hue_center=SKIN_HUE_CENTER,
        skin_hue_pull=round(skin_hue_pull, 3),
        skin_chroma_scale=round(skin_chroma_scale, 3),
    )


def print_report(title: str, field: LookField, lab_a: np.ndarray, lab_r: np.ndarray) -> None:
    L_a = lab_a[:, 0]
    C_a = np.hypot(lab_a[:, 1], lab_a[:, 2])
    h_a = np.degrees(np.arctan2(lab_a[:, 2], lab_a[:, 1])) % 360.0
    C_r = np.hypot(lab_r[:, 1], lab_r[:, 2])
    h_r = np.degrees(np.arctan2(lab_r[:, 2], lab_r[:, 1])) % 360.0
    dh = (h_r - h_a + 180.0) % 360.0 - 180.0
    cr = C_r / np.maximum(C_a, 1e-5)
    mid = (L_a > 0.35) & (L_a < 0.75) & (C_a > 0.05) & (C_a < 0.20)

    print(f"\n===== {title} =====")
    print("hue sector (mid-L, moderate C):  Δhue°   C-ratio   n")
    for i, lo in enumerate(range(0, 360, 30)):
        m = mid & (h_a >= lo) & (h_a < lo + 30)
        if np.count_nonzero(m) >= 4:
            print(
                f"  {lo:3d}-{lo+30:3d}°: {field.hue_rotation_deg[i]:+7.2f}  "
                f"{field.chroma_ratio[i]:7.3f}  {np.count_nonzero(m):4d}"
            )
    print(
        f"shadows: C-ratio={field.shadow_chroma_ratio:.3f}  "
        f"cool Δa={field.shadow_cool_a:+.4f} Δb={field.shadow_cool_b:+.4f}  "
        f"L ramp {field.shadow_l_lo:.2f}-{field.shadow_l_hi:.2f}"
    )
    print(
        f"highlights: C-ratio={field.highlight_chroma_ratio:.3f}  "
        f"L ramp {field.highlight_l_lo:.2f}-{field.highlight_l_hi:.2f}"
    )
    print(f"sat knee: C>{field.sat_knee_c:.2f} relief×{field.sat_knee_relief:.3f}")
    skin = (h_a >= SKIN_HUE_LO) & (h_a <= SKIN_HUE_HI) & mid
    if np.count_nonzero(skin) >= 6:
        print(
            f"skin {SKIN_HUE_LO:.0f}-{SKIN_HUE_HI:.0f}°: pull={field.skin_hue_pull:.3f}  "
            f"chroma×{field.skin_chroma_scale:.3f}  "
            f"spread {np.std(h_a[skin]):.1f}°→{np.std(h_r[skin]):.1f}°"
        )
    print(f"global ΔL median {np.median(lab_r[:, 0] - lab_a[:, 0]):+.3f}")


def validate_fit(look_id: str, field: LookField, lab_a: np.ndarray, lab_r: np.ndarray) -> dict[str, float]:
    """Apply measured field on AgX Oklab and compare to ARRI target."""
    from dngscan import look as look_mod

    L, a, b = lab_a[:, 0], lab_a[:, 1], lab_a[:, 2]
    old = look_mod.LOOK_FIELDS[look_id]
    look_mod.LOOK_FIELDS[look_id] = field
    try:
        _, a2, b2 = apply_look_oklab(L, a, b, look_id, 1.0)
    finally:
        look_mod.LOOK_FIELDS[look_id] = old

    fit = np.stack([L, a2, b2], axis=1)
    delta = fit - lab_r
    chroma_mask = np.hypot(lab_a[:, 1], lab_a[:, 2]) > 0.03
    return {
        "delta_l_rmse": float(np.sqrt(np.mean(delta[:, 0] ** 2))),
        "delta_ab_rmse": float(np.sqrt(np.mean(np.sum(delta[chroma_mask, 1:] ** 2, axis=1)))) if np.any(chroma_mask) else 0.0,
        "hue_rmse_deg": float(
            np.sqrt(
                np.mean(
                    (
                        (np.degrees(np.arctan2(fit[chroma_mask, 2], fit[chroma_mask, 1])) - np.degrees(np.arctan2(lab_r[chroma_mask, 2], lab_r[chroma_mask, 1])) + 180)
                        % 360
                        - 180
                    )
                    ** 2
                )
            )
        )
        if np.any(chroma_mask)
        else 0.0,
    }


def emit_python(fields: dict[str, LookField]) -> str:
    lines = ["LOOK_FIELDS: dict[str, LookField] = {"]
    for key, f in fields.items():
        lines.append(f'    "{key}": LookField(')
        lines.append(f"        hue_rotation_deg={f.hue_rotation_deg},")
        lines.append(f"        chroma_ratio={f.chroma_ratio},")
        lines.append(f"        mid_chroma_ratio={f.mid_chroma_ratio},")
        lines.append(f"        shadow_chroma_ratio={f.shadow_chroma_ratio},")
        lines.append(f"        highlight_chroma_ratio={f.highlight_chroma_ratio},")
        lines.append(f"        shadow_cool_a={f.shadow_cool_a},")
        lines.append(f"        shadow_cool_b={f.shadow_cool_b},")
        lines.append(f"        shadow_l_lo={f.shadow_l_lo},")
        lines.append(f"        shadow_l_hi={f.shadow_l_hi},")
        lines.append(f"        highlight_l_lo={f.highlight_l_lo},")
        lines.append(f"        highlight_l_hi={f.highlight_l_hi},")
        lines.append(f"        sat_knee_c={f.sat_knee_c},")
        lines.append(f"        sat_knee_relief={f.sat_knee_relief},")
        lines.append(f"        skin_hue_lo={f.skin_hue_lo},")
        lines.append(f"        skin_hue_hi={f.skin_hue_hi},")
        lines.append(f"        skin_hue_center={f.skin_hue_center},")
        lines.append(f"        skin_hue_pull={f.skin_hue_pull},")
        lines.append(f"        skin_chroma_scale={f.skin_chroma_scale},")
        lines.append("    ),")
    lines.append("}")
    return "\n".join(lines)


def run_self_tests() -> None:
    lc3_18 = float(logc3_encode(np.array([0.18]))[0])
    lc4_18 = float(logc4_encode(np.array([0.18]))[0])
    print(f"[self-test] LogC3(0.18)={lc3_18:.4f} (published 0.391)   LogC4(0.18)={lc4_18:.4f} (published 0.278)")
    if abs(lc3_18 - 0.391) >= 0.002 or abs(lc4_18 - 0.278) >= 0.002:
        raise SystemExit("LogC constants wrong")
    for name, m in (("AWG3", AWG3_TO_XYZ), ("AWG4", AWG4_TO_XYZ)):
        w = m @ [1, 1, 1]
        print(f"[self-test] {name} white -> XYZ {np.round(w, 4)} (expect ~[0.9505, 1.0, 1.0891])")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emit", choices=("python", "json"), help="emit measured LookField data")
    parser.add_argument("--out", type=Path, help="output path for --emit json")
    parser.add_argument("--validate", action="store_true", help="report look fit error vs ARRI")
    args = parser.parse_args()

    run_self_tests()
    scene_srgb = build_scene_sweep()
    scene_xyz = scene_srgb @ np.asarray(dg.RGB_TO_XYZ["sRGB"]).T
    lab_a = render_agx_oklab(scene_xyz)

    measured: dict[str, LookField] = {}
    for look_id, (title, fname, enc) in LUTS.items():
        lut_path = ASSETS / fname
        if not lut_path.is_file():
            print(f"skip {look_id}: missing {lut_path}", file=sys.stderr)
            continue
        lab_r = render_arri_oklab(scene_xyz, lut_path, enc)
        neutral_rows = np.arange(0, len(scene_srgb), 1 + 36 * 5)
        tint = np.abs(lab_r[neutral_rows, 1:]).max()
        print(f"\n===== {title} =====")
        print(f"[sanity] max |a,b| on neutral ladder: {tint:.4f} (should be ~<0.01)")
        field = measure_look_field(lab_a, lab_r)
        measured[look_id] = field
        print_report(title, field, lab_a, lab_r)
        if args.validate:
            stats = validate_fit(look_id, field, lab_a, lab_r)
            print(f"[validate] ΔL RMSE={stats['delta_l_rmse']:.4f}  Δab RMSE={stats['delta_ab_rmse']:.4f}  hue RMSE={stats['hue_rmse_deg']:.2f}°")

    if args.emit == "python":
        print("\n# --- paste into dngscan/look.py ---")
        print(emit_python(measured))
    elif args.emit == "json":
        payload = {k: asdict(v) for k, v in measured.items()}
        text = json.dumps(payload, indent=2)
        if args.out:
            args.out.write_text(text + "\n", encoding="utf-8")
            print(f"wrote {args.out}")
        else:
            print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
