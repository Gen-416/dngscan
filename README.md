# dngscan

[中文](README.zh-CN.md)

A physically-grounded RAW/DNG analyzer and **AgX** tone-mapping exporter. It reads a
camera raw file, measures what the sensor actually captured (dynamic range, per-channel
clipping, SNR, gamut pressure), and renders that scene-linear signal to an 8-bit JPEG
through a single AgX view transform — optionally with a **grade** (chromatic look or
display filter) — from the command line or a small local web GUI.

It began as a diagnostic tool (the six-panel PNG dashboard) and grew into a way to
produce finished JPEGs directly, without round-tripping through a raw editor.

## What it does

- **Diagnostics** — a six-panel PNG dashboard: SNR-vs-stops curves, per-channel raw
  distributions, RGB exposure histograms, gamut-overflow risk per output space, a
  spatial exposure-zone map, and a clipped-channel highlight map, plus per-channel
  full-well / clip / black-level / white-balance readouts.
- **AgX export** — Rec.2020-native AgX view transform: inset → log2 → sigmoid →
  outset. Channel crosstalk gives smooth highlight desaturation and AgX's signature hue
  flourish. All JPEG output uses this pipeline.
- **Pre-AgX scene transform (experimental)** — optional `--scene-transform arri_skin_d55`
  runs in scene-linear Rec.2020 after camera colour interpretation and before AgX,
  blending constrained 3x3 matrices inside skin/cyan chromaticity masks. Off by default.
- **Grades (mutually exclusive)** — one optional layer on top of AgX (`--grade`):
  - **Chromatic looks** — measured Oklab geometry from official LUTs (Fujifilm film sims,
    ARRI Classic / Reveal). Tone stays AgX; only hue / saturation / skin shaping.
  - **Display filters** — full log-encoded output transforms (Kodak 2383 FPE, RED IPP2)
    sampled from `.cube` files after Cineon / Log3G10 encode.
- **Hue-preserving gamut fit** — output fitting uses Oklab adaptive-L0 clipping (hold
  hue, reduce chroma) instead of per-channel clipping. Works for sRGB and Display P3.
- **High-quality demosaic on export** — full-res exports use `--demosaic auto` (DHT
  preferred, libraw-native for non-Bayer / X-Trans sensors) or a manual algorithm;
  preview uses a light demosaic. Interpolation quality only — **no noise reduction**.
- **Local web GUI** (`python -m dngscan.gui`) — pick a file, exposure, grade, quality,
  demosaic and output gamut; live preview; per-file exposure-headroom estimate; sRGB or
  Display P3; highlight handling (clip / blend / reconstruct).
- **Optional Ultra HDR JPEG** — ISO/Ultra HDR gain-map output with an SDR fallback.
  Grades are SDR-only today. SDR JPEG remains the default.

## Processing pipeline

Everything through AgX is fixed. `--grade` picks **one** post-AgX path — the Oklab and
log-encode branches are mutually exclusive implementations for two different LUT families,
not two layers you can stack.

```text
┌─────────────────────────────────────────────────────────────┐
│ ① RAW restore                                               │
│    DNG ──► demosaic ──► WB ──► color matrix ──► scene Rec.2020│
└────────────────────────────┬────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ ② Analysis + exposure                                       │
│    analyze() · EV manual/auto · compute_exposure_gain(agx)  │
└────────────────────────────┬────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ ②b Pre-AgX scene transform (optional)                       │
│    scene Rec.2020 ──► skin/cyan chroma mask ──► constrained M│
└────────────────────────────┬────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ ③ AgX  (always)                                             │
│    scene Rec.2020 ──► AgX core ──► mapped Rec.2020          │
└────────────────────────────┬────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ ③b grade  `--grade` · pick exactly one · same AgX input     │
│                                                             │
│   none ──────────────► rec2020_to_output (AgX display only) │
│                                                             │
│   chromatic look ────► rec2020_to_output                    │
│        (Fujifilm / ARRI)   └──► Oklab + LookField           │
│                              hue / chroma / skin only; L fixed│
│                              (pre-measured; no .cube at run) │
│                                                             │
│   display filter ────► log encode ──► sample .cube ──► decode│
│        (Kodak / RED)     Cineon+709  or  Log3G10+RWG        │
│                          full output transform; tone+color  │
│                          blended with AgX display at strength│
│                                                             │
│   ✕ never chromatic look + display filter on the same export │
└────────────────────────────┬────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ ④ Display encode                                            │
│    gamut fit · sRGB/P3 OETF + TPDF dither · JPEG / Ultra HDR│
└─────────────────────────────────────────────────────────────┘
```

**Why two grade mechanisms?** Both choices sit on the same AgX render. Fujifilm / ARRI
official LUTs were **measured** into Oklab LookFields — they only describe chromatic
geometry relative to AgX, so runtime work stays in Oklab with **L untouched**. Kodak /
RED cubes are **full** log-in → display-out transforms (tone and saturation together);
they must be sampled after the correct log encode. Feeding those cubes through the
LookField extractor collapses saturation, so they get a separate log → `.cube` path instead.

## Design notes

A few choices worth knowing:

- **Exposure is a fixed constant, never content-adaptive.** AgX anchors a nominally-exposed
  mid gray onto 0.18 with a constant scalar; `--ev` adds a manual offset or `auto` aligns
  median to 18% gray with highlight protection. A dark scene stays dark.
- **Scene-linear Rec.2020 throughout.** The export buffer stays in a wide working
  space so saturated highlights are not clipped to sRGB before tone mapping. AgX's
  inset/outset are conjugated into Rec.2020 so neutrals stay neutral.
- **TPDF-dithered 8-bit quantization** to avoid banding in smooth gradients.
- **Hue-preserving gamut fit.** Colors outside the output gamut are brought in with Oklab
  adaptive-L0 clipping (hold hue, reduce chroma) rather than per-channel clipping, which
  skews hue on saturated colors. Applied in every mode, for both sRGB and Display P3.
- **Demosaicing is reconstruction, not denoising.** Bayer sensors can use DHT on export;
  non-Bayer (e.g. Fujifilm X-Trans) keeps libraw's native path. No smoothing, no NR.
- **Gain-map HDR is additive.** The SDR base image is the same rendered output, while
  the HDR numerator keeps midtones equal to SDR and releases only highlight headroom.
  HDR output is forced to Display P3 and defaults to +3 EV headroom.
- **Per-channel analysis** — full-well and clip thresholds are reconstructed per
  channel (empirical saturation pile when present, metadata white level as a
  fallback for unclipped scenes).
- **Sensor priors (best-effort).** When the camera is in the priors table (currently
  Sigma fp, from published PhotonsToPhotos measurements), the analysis reports
  electron-domain figures (e-/DN gain, measured noise floor in e-, read-noise and PDR
  priors) and gently bounds the tone plan's DR budget with the published PDR. Unknown
  cameras fall back to pure single-frame estimates.
- **RAW health check.** The dual-green difference plane (scene cancels, noise remains)
  is tested for lag-1 spatial correlation — a per-frame verdict on noise reduction baked
  into the raw file — plus a missing-DN-code (requantization) check. Diagnostics only.
- **Fixed white balance option.** `--wb daylight` uses libraw's calibrated daylight
  multipliers as a film-style fixed balance (consistent across a whole shoot); the
  as-shot balance is always reported as light-source testimony, including its deviation
  from daylight. Default remains the camera's as-shot balance.
- **Analysis matches the export.** Render-dependent stats (luminance/EV distribution,
  gamut-overflow risk, and the auto tone plan's inputs) are measured on a render that uses
  the same demosaic and highlight mode as your export, so they describe the image you
  actually get. Raw/CFA-domain analysis (clip %, saturation pile, SNR, noise floor) stays
  independent of demosaic and highlight — it reports what the sensor physically captured.

Metrics are single-frame estimates (not photon-transfer measurements); bit depth is
not the same as usable dynamic range.

## Install

dngscan does not bundle Python or Homebrew dependencies inside the repo. Keep the
system environment normal, and keep project-specific assets in this project folder.

Requires Python 3.10+ and:

```
pip install -r requirements.txt
```

(`numpy`, `rawpy`, `matplotlib`, `pillow`.) The GUI runs in your browser and does
**not** need Tkinter.

To refit the spectral pre-AgX scene-transform matrix, install the optional calibration
dependency:

```bash
pip install -r requirements-calibration.txt
```

Ultra HDR output uses macOS ImageIO/PyObjC when available, and falls back to Google's
`libultrahdr` CLI if installed:

```bash
brew install libultrahdr
```

Project layout:

```text
dngscan/
  cli.py                # CLI entry point
  agx.py                # AgX inset/outset, log curve and sigmoid core
  look.py               # chromatic LookField layer (Oklab)
  scene_transform.py    # scene-linear pre-AgX transforms
  scene_transform_presets.json # demo ARRI skin prefeed preset
  display_filter.py     # Kodak / RED display LUT filters
  grade.py              # unified grade picker (look OR filter)
  render.py / export.py # scene → AgX → JPEG / Ultra HDR
  gui/                  # local web GUI
dngscan_assets/
  look_fields.json      # user-measured looks (gitignored)
  vendor_luts/          # downloaded .cube files (gitignored)
  spectral/             # pre-AgX calibration CSVs: SSF/QE/IR-cut/reflectance
  darktable_agx.*       # local AgX reference copies
tools/
  calibrate_skin_matrix.py # spectral CSV → matrix/mask JSON
```

## Usage

Command line:

```bash
# Diagnostic PNG only
python -m dngscan photo.dng

# AgX JPEG, +0.5 EV, Display P3
python -m dngscan photo.dng --jpeg out.jpg --ev 0.5 --output-gamut p3

# Fujifilm Velvia look (chromatic geometry on AgX)
python -m dngscan photo.dng --jpeg out.jpg --grade fuji_velvia --grade-strength 1.0

# Optical warm/cyan look: cyan-biased environment, warm skin/highlights
python -m dngscan photo.dng --jpeg out.jpg --grade optic_warm_cyan --grade-strength 1.0

# Kodak 2383 display filter (log-encoded .cube)
python -m dngscan photo.dng --jpeg out.jpg --grade kodak_2383_d65

# Pre-AgX ARRI-style skin prefeed (experimental; compare separately from grade)
python -m dngscan photo.dng --jpeg out.jpg --scene-transform arri_skin_d55 \
  --scene-transform-strength 1.0

# Force demosaic (default auto → DHT on Bayer; export only)
python -m dngscan photo.dng --jpeg out.jpg --demosaic dht

# Ultra HDR gain-map JPEG (no grade; SDR base forced to Display P3)
python -m dngscan photo.dng --jpeg out_hdr.jpg --highlight-mode reconstruct \
  --output-format ultrahdr --hdr-headroom 3

# Diagnostics + metrics CSV alongside JPEG
python -m dngscan photo.dng --jpeg out.jpg --scan --csv metrics.csv
```

Local GUI:

```bash
python -m dngscan.gui   # starts a localhost server and opens the browser
```

For WeChat/QQ delivery, use original-file or file transfer if you want the HDR gain
map to survive. Moments/feed-style uploads usually recompress to SDR and strip the
gain map.

## Grades

`--grade NAME` picks **one** optional style (`--grade-strength 0–1.5`). Chromatic looks
and display filters are mutually exclusive.

**Chromatic looks** (`classic`, `reveal`, `fuji_*`, …) apply a measured Oklab field on the
AgX render. Built-in ARRI fields come from official display LUT geometry; Fujifilm fields
are measured from F-Log2 film-sim `.cube` files. **No LUT is sampled at export time** for
looks — only pre-measured hue/chroma parameters in `dngscan_assets/look_fields.json`.

`optic_warm_cyan` is different: it is a hand-authored creative look, not an official
vendor LUT measurement. It keeps AgX tone mapping, then biases low-chroma environment
tones toward cyan/blue-green, protects warm skin reds/yellows, and damps non-skin magenta
spill. It is intended for ARRI-like skin/environment separation without shipping or
sampling proprietary LUTs.

**Display filters** (`kodak_2383_d65`, `red_ipp2_rec709_medium`) are full output transforms:
AgX → log encode → vendor `.cube` → display decode → blend. These cannot be reduced to a
chromatic look (measuring them as LookFields collapses saturation).

Add a chromatic look from any official Log→display `.cube` you download:

```bash
# example: Fujifilm ETERNA (F-Log2 → ETERNA .cube from Fujifilm's site)
python tools/extract_arri_look.py --lut path/to/eterna.cube --source flog2 \
  --name fuji_eterna --validate --append-json
```

Supported `--source` encodings: `logc3, logc4, slog3, vlog, flog, flog2, cineon, log3g10`.
The tool warns when `mid_chroma_ratio < 0.25` (full output transform — use a display
filter instead). Measurement compares the LUT against AgX in Oklab with L-normalized
saturation so the field captures chromatic character without the LUT's tone curve.

Place display-filter `.cube` files under `dngscan_assets/vendor_luts/` (see
`display_filter.py` for expected paths).

## Pre-AgX Scene Transforms

`--scene-transform` is a scene-linear input transform, not a display filter. The built-in
`arri_skin_d55` preset is generated by `tools/calibrate_skin_matrix.py` from the replaceable
CSV inputs in `dngscan_assets/spectral/`: ALEV3 SSF, IMX410 QE, Sigma fp hot-mirror
transmission, and skin/cyan reflectance spectra. Runtime export only reads
`dngscan/scene_transform_presets.json`; it does not need `colour-science` or `scipy`.

Regenerate the demo preset:

```bash
python tools/calibrate_skin_matrix.py --out dngscan/scene_transform_presets.json
```

Write or refresh the bootstrap CSV bundle:

```bash
python tools/calibrate_skin_matrix.py --write-bootstrap-csv dngscan_assets/spectral
```

For serious calibration, replace the bootstrap CSVs with digitized ALEV3 SSF, ZWO
ASI2400MC / IMX410 QE, measured Sigma fp hot-mirror transmission, and a licensed real skin
reflectance library. The script also accepts `--skin-dir` / `--cyan-dir` directories and can
use `colour-science` for D55/A illuminants and CIE 1931 CMFs. The current CSVs are still
bootstrap approximations; their purpose is to make the chain data-driven:
IMX410-to-ALEV skin-subspace difference → constrained matrix → pre-AgX scene input.

## License & attribution

Licensed under **GPL-3.0-or-later** (see [LICENSE](LICENSE)). The AgX implementation
ports portions of [darktable](https://github.com/darktable-org/darktable)'s GPL-3.0-or-later
AgX code. See [NOTICE.md](NOTICE.md) for third-party assets.
