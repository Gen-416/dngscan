# dngscan

A physically-grounded RAW/DNG analyzer and tone-mapping exporter. It reads a camera
raw file, measures what the sensor actually captured (dynamic range, per-channel
clipping, SNR, gamut pressure), and can render that scene-linear signal to an 8-bit
JPEG through one of four tone-mapping pipelines — either from the command line or a
small local web GUI.

It began as a diagnostic tool (the six-panel PNG dashboard) and grew into a way to
produce finished JPEGs directly, without round-tripping through a raw editor.

## What it does

- **Diagnostics** — a six-panel PNG dashboard: SNR-vs-stops curves, per-channel raw
  distributions, RGB exposure histograms, gamut-overflow risk per output space, a
  spatial exposure-zone map, and a clipped-channel highlight map, plus per-channel
  full-well / clip / black-level / white-balance readouts.
- **Four export pipelines** (`--jpeg-mode`):
  - `neutral` — minimal-loss reference: scene-linear → display encode, no tone curve.
    Faithful, but clips highlights (no shoulder); meant as a baseline, not a finished look.
  - `smart` — analysis-driven highlight shoulder + hue-preserving chroma easing,
    computed in the output color space with same-space luminance.
  - `agx` — AgX view transform with the Rec.2020-native Blender/EaryChow matrices:
    inset (primaries rotation + attenuation) → log2 → sigmoid → linearize → 40%
    hue-mix → outset in linear light. The channel crosstalk gives AgX's smooth
    highlight desaturation and its signature hue flourish.
  - `tony` — the Tony McMapface display-referred 3D LUT.
- **Hue-preserving gamut fit** — every mode ends by fitting out-of-gamut colors into the
  output space with Oklab adaptive-L0 clipping (hold hue, reduce chroma) instead of
  per-channel clipping, which skews hue on saturated colors. Works for sRGB and Display P3.
- **High-quality demosaic on export** — full-res exports use `--demosaic auto` (DHT
  preferred, libraw-native for non-Bayer sensors) or a manual algorithm; the fast preview
  uses a light demosaic. This selects interpolation *quality* only — no noise reduction is
  ever applied.
- **Local web GUI** (`python -m dngscan.gui`) — pick a file, mode, exposure, quality,
  demosaic and output gamut; live preview; per-file exposure-headroom estimate; sRGB or
  Display P3 output; highlight handling (clip / blend / reconstruct). Browser-based, no Tk.
- **Optional Ultra HDR JPEG** — writes JPEG-based gain-map HDR output with a normal
  SDR fallback image plus an ISO/Ultra HDR gain map. SDR JPEG remains the default.

## Design notes

A few choices worth knowing:

- **Exposure is a fixed constant, never content-adaptive.** The tone modes anchor a
  nominally-exposed mid gray onto 0.18 with a constant scalar; `--ev` adds a manual
  offset. A dark scene stays dark — the tool never auto-brightens to "average" and
  never changes your capture intent.
- **Scene-linear Rec.2020 throughout.** The export buffer stays in a wide working
  space so saturated highlights are not clipped to sRGB before tone mapping. AgX's
  inset/outset are conjugated into Rec.2020 so neutrals stay neutral.
- **TPDF-dithered 8-bit quantization** to avoid banding in smooth gradients.
- **Hue-preserving gamut fit.** Colors outside the output gamut are brought in with Oklab
  adaptive-L0 clipping (hold hue, reduce chroma) rather than per-channel clipping, which
  skews hue on saturated colors. Applied in every mode, for both sRGB and Display P3.
- **Demosaicing is reconstruction, not denoising.** Every raw must be demosaiced
  (interpolating the two missing colors at each Bayer pixel) — it is mandatory, never
  optional. `--demosaic` only selects interpolation *quality* (default `auto` → DHT on the
  full-res export, libraw-native for non-Bayer sensors); it applies no smoothing. The
  pipeline performs **no noise reduction at all** (FBDD off, no median filtering): a
  high-quality demosaic preserves detail and noise, it never removes them.
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
  __main__.py           # CLI entry point: python -m dngscan
  core.py               # RAW analysis, tone planning, Tony/export pipeline
  agx.py                # AgX inset/outset, log curve and sigmoid core
  gui.py                # GUI entry point: python -m dngscan.gui
dngscan_assets/
  README.md             # asset notes
  TONY_LICENSE-MIT.md   # Tony McMapface MIT license text
  tony_mc_mapface.spi3d # Tony LUT
  darktable_agx.*       # local AgX reference copies
```

## Usage

Command line:

```bash
# Diagnostic PNG only
python -m dngscan photo.dng

# Export a JPEG with the AgX pipeline, +0.5 EV, Display P3
python -m dngscan photo.dng --jpeg out.jpg --jpeg-mode agx --ev 0.5 --output-gamut p3

# Force a specific demosaic algorithm (default is auto -> DHT; export only)
python -m dngscan photo.dng --jpeg out.jpg --jpeg-mode agx --demosaic dht

# Export an ISO/Ultra HDR gain-map JPEG. The SDR base is forced to Display P3.
python -m dngscan photo.dng --jpeg out_hdr.jpg --jpeg-mode agx --highlight-mode reconstruct \
  --output-format ultrahdr --hdr-headroom 3

# Faithful reference, also write the diagnostic PNG and a metrics CSV
python -m dngscan photo.dng --jpeg out.jpg --jpeg-mode neutral --scan --csv metrics.csv
```

Local GUI:

```bash
python -m dngscan.gui   # starts a localhost server and opens the browser
```

For WeChat/QQ delivery, use original-file or file transfer if you want the HDR gain
map to survive. Moments/feed-style uploads usually recompress to SDR and strip the
gain map.

## Looks (chromatic layer on top of AgX)

`--look {classic,reveal,...}` applies a purely chromatic Oklab field on the agx render
(`--look-strength 0–1.5`). The built-in `classic` / `reveal` fields are geometry measured
from ARRI's official display LUTs (K1S1 and Reveal); no LUT data ships with the repo.

**Add your own look** from any official Log→Rec.709 display LUT you download:

```bash
# example: Fujifilm ETERNA (F-Log → ETERNA BT.709 .cube from Fujifilm's site)
python tools/extract_arri_look.py --lut path/to/eterna.cube --source flog \
  --name eterna --validate --append-json
```

Supported `--source` encodings: `logc3, logc4, slog3, vlog, flog, flog2` (each
self-tests its gray anchor and gamut white point). The measured field is written to
`dngscan_assets/look_fields.json` (user-local, gitignored) and appears automatically in
the CLI `--look` choices and the GUI dropdown on restart. Worthwhile official downloads:
Fujifilm F-Log→ETERNA, Sony S-Log3→s709 (Venice look), Panasonic V-Log→V-709.
The measurement compares the LUT against dngscan's AgX in Oklab with L-normalized
saturation, so a look field captures the LUT's chromatic character without its tone.

## Tony McMapface LUT

The `tony` mode needs `tony_mc_mapface.spi3d`. Keep it at
`./dngscan_assets/tony_mc_mapface.spi3d`, or pass `--tony-lut PATH`. The bundled LUT
is redistributed under the upstream MIT license in
`dngscan_assets/TONY_LICENSE-MIT.md`.

## License & attribution

Licensed under **GPL-3.0-or-later** (see [LICENSE](LICENSE)). The AgX mode ports
portions of [darktable](https://github.com/darktable-org/darktable)'s GPL-3.0-or-later
AgX implementation, which is why the combined work is GPL. The Tony McMapface LUT is
an external asset dual-licensed Apache-2.0 OR MIT by
[h3r2tic/tony-mc-mapface](https://github.com/h3r2tic/tony-mc-mapface). See
[NOTICE.md](NOTICE.md) for details.
