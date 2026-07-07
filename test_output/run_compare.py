#!/usr/bin/env python3
"""Batch export + metrics for DNG comparison (dev harness)."""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dngscan as dg
from dngscan.grade import resolve_grade

FILES = [
    Path("/Users/itoshikigen/Pictures/_SDI0199.DNG"),
    Path("/Users/itoshikigen/Pictures/_SDI0200.DNG"),
    Path("/Users/itoshikigen/Pictures/_SDI0206.DNG"),
]

JOBS = [
    ("agx", "none", "p3"),
    ("agx_classic", "look:classic", "p3"),
    ("agx_reveal", "look:reveal", "p3"),
    ("agx_fuji_velvia", "look:fuji_velvia", "p3"),
    ("agx_kodak", "filter:kodak_2383_d65", "p3"),
    ("agx_red", "filter:red_ipp2_rec709_medium", "p3"),
]

JPEG_QUALITY = 100
JPEG_SUBSAMPLING = 0  # 4:4:4


def run_one(path: Path, outdir: Path) -> list[dict]:
    rows: list[dict] = []
    stem = path.stem
    bundle = dg.load_raw(path, "reconstruct", demosaic="auto", wb_mode="camera")
    analysis, y, ev = dg.analyze(bundle, 4)
    base = {
        "file": stem,
        "make": bundle.shot_make,
        "model": bundle.shot_model,
        "iso": bundle.shot_iso,
        "prior_id": analysis.prior_id,
        "median_vs_gray_ev": round(analysis.median_vs_gray_ev, 2),
        "usable_dr_ev": round(analysis.usable_dr_ev, 2),
        "usable_dr_eff_ev": round(analysis.usable_dr_eff_ev, 2) if analysis.usable_dr_eff_ev == analysis.usable_dr_eff_ev else None,
        "clip_pct_max": round(max(analysis.clip_pct.values()) if analysis.clip_pct else 0, 3),
        "ev_median": round(analysis.ev_median, 2),
        "ev_p999": round(analysis.ev_p999, 2),
        "gamut_p3_pct": round(analysis.gamut_out_pct.get("P3", 0), 3),
        "health_lag1": round(analysis.health_lag1_corr, 4) if analysis.health_lag1_corr == analysis.health_lag1_corr else None,
    }
    rows.append({"kind": "analysis", **base})

    for suffix, grade, gamut in JOBS:
        look, look_strength, display_filter, filter_strength = resolve_grade(grade, 1.0)
        auto = dg.compute_auto_ev(
            bundle,
            analysis,
            gamut,
            look=look,
            look_strength=look_strength,
            display_filter=display_filter,
            filter_strength=filter_strength,
        )
        bundle.exposure_gain = dg.compute_exposure_gain("agx", auto.ev)
        plan = dg.plan_for_mode(bundle, analysis, "agx", gamut)
        jpg = outdir / f"{stem}_{suffix}_p3.jpg" if gamut == "p3" else outdir / f"{stem}_{suffix}.jpg"
        if gamut == "srgb" and suffix != "agx":
            jpg = outdir / f"{stem}_{suffix}_srgb.jpg"
        t0 = time.perf_counter()
        dg.export_jpeg(
            path,
            jpg,
            JPEG_QUALITY,
            bundle,
            analysis,
            plan,
            gamut,
            "sdr",
            subsampling=JPEG_SUBSAMPLING,
            look=look,
            look_strength=look_strength,
            display_filter=display_filter,
            filter_strength=filter_strength,
        )
        elapsed = time.perf_counter() - t0
        anchored = analysis.median_vs_gray_ev + math.log2(max(bundle.exposure_gain, 1e-12))
        rows.append(
            {
                "kind": "export",
                "file": stem,
                "suffix": suffix,
                "mode": "agx",
                "grade": grade,
                "look": look,
                "display_filter": display_filter,
                "gamut": gamut,
                "quality": JPEG_QUALITY,
                "chroma": "444",
                "ev": round(auto.ev, 2),
                "ev_boost": round(auto.ev_boost, 2),
                "ev_median_target": round(auto.ev_median_target, 2),
                "highlight_limited": auto.highlight_limited,
                "anchored_median_ev": round(anchored, 2),
                "jpg": str(jpg.name),
                "bytes": jpg.stat().st_size if jpg.is_file() else 0,
                "seconds": round(elapsed, 2),
            }
        )
    return rows


def main() -> int:
    dg.require_dependencies()
    all_rows: list[dict] = []
    root = Path(__file__).parent
    for path in FILES:
        outdir = root / path.stem
        outdir.mkdir(parents=True, exist_ok=True)
        print(f"=== {path.name} ===", flush=True)
        rows = run_one(path, outdir)
        all_rows.extend(rows)
        for r in rows:
            if r["kind"] == "analysis":
                print(
                    f"  {r['make']} {r['model']} ISO{r['iso']} prior={r['prior_id']} "
                    f"DR={r['usable_dr_ev']} clip={r['clip_pct_max']}% "
                    f"ev_med={r['ev_median']} vs_gray={r['median_vs_gray_ev']} health={r['health_lag1']}",
                    flush=True,
                )
            else:
                lim = " 高光限制" if r.get("highlight_limited") else ""
                print(
                    f"  {r['suffix']}: EV {r['ev']:+.2f} (目标{r['ev_median_target']:+.2f})"
                    f" 锚定{r['anchored_median_ev']:+.2f}{lim} · {r['bytes']//1024}KB {r['seconds']}s",
                    flush=True,
                )
    (root / "compare_results.json").write_text(json.dumps(all_rows, indent=2), encoding="utf-8")
    print(f"\n设置: quality={JPEG_QUALITY}, 4:4:4, EV=auto, highlight=reconstruct", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
