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
│ ③ AgX                                                       │
│    scene Rec.2020 ──► AgX core ──► mapped Rec.2020          │
└────────────────────────────┬────────────────────────────────┘
                             ▼
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
           [none]      chromatic look    display filter
                      │                  │
              rec2020_to_output    log encode → .cube → decode
                      │                  │
              Oklab + LookField      Kodak: Cineon + Rec.709
              (L untouched)          RED: Log3G10 + RWG
                      │                  │
              └──────────────┬───────────┘
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ ④ Display encode                                            │
│    gamut fit · sRGB/P3 OETF + TPDF dither · JPEG / Ultra HDR│
└─────────────────────────────────────────────────────────────┘
```

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
  display_filter.py     # Kodak / RED display LUT filters
  grade.py              # unified grade picker (look OR filter)
  render.py / export.py # scene → AgX → JPEG / Ultra HDR
  gui/                  # local web GUI
dngscan_assets/
  look_fields.json      # user-measured looks (gitignored)
  vendor_luts/          # downloaded .cube files (gitignored)
  darktable_agx.*       # local AgX reference copies
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

# Kodak 2383 display filter (log-encoded .cube)
python -m dngscan photo.dng --jpeg out.jpg --grade kodak_2383_d65

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

## License & attribution

Licensed under **GPL-3.0-or-later** (see [LICENSE](LICENSE)). The AgX implementation
ports portions of [darktable](https://github.com/darktable-org/darktable)'s GPL-3.0-or-later
AgX code. See [NOTICE.md](NOTICE.md) for third-party assets.
