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
    Faithful, but hard-clips highlights; meant as a baseline, not a finished look.
  - `smart` — analysis-driven highlight shoulder + hue-preserving chroma easing,
    computed in the output color space with same-space luminance.
  - `agx` — AgX view transform (inset → log2 → sigmoid → outset), run natively in
    Rec.2020. The inset/outset channel crosstalk gives AgX's smooth highlight
    desaturation instead of hard per-channel clipping.
  - `tony` — the Tony McMapface display-referred 3D LUT.
- **Local web GUI** (`dngscan_gui.py`) — pick a file, mode, exposure and quality;
  live preview; per-file exposure-headroom estimate; sRGB or Display P3 output;
  highlight handling (clip / blend / reconstruct). Browser-based, no Tk required.

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
- **Per-channel analysis** — full-well and clip thresholds are reconstructed per
  channel (empirical saturation pile when present, metadata white level as a
  fallback for unclipped scenes).

Metrics are single-frame estimates (not photon-transfer measurements); bit depth is
not the same as usable dynamic range.

## Install

Requires Python 3.10+ and:

```
pip install -r requirements.txt
```

(`numpy`, `rawpy`, `matplotlib`, `pillow`.) The GUI runs in your browser and does
**not** need Tkinter.

## Usage

Command line:

```bash
# Diagnostic PNG only
python dngscan.py photo.dng

# Export a JPEG with the AgX pipeline, +0.5 EV, Display P3
python dngscan.py photo.dng --jpeg out.jpg --jpeg-mode agx --ev 0.5 --output-gamut p3

# Faithful reference, also write the diagnostic PNG and a metrics CSV
python dngscan.py photo.dng --jpeg out.jpg --jpeg-mode neutral --scan --csv metrics.csv
```

Local GUI:

```bash
python dngscan_gui.py   # starts a localhost server and opens the browser
```

## Tony McMapface LUT

The `tony` mode needs `tony_mc_mapface.spi3d`, which is **not** bundled. Download it
from [h3r2tic/tony-mc-mapface](https://github.com/h3r2tic/tony-mc-mapface/tree/main/OCIO/LUTs)
and place it at `~/dngscan_assets/tony_mc_mapface.spi3d`, or pass `--tony-lut PATH`.

## License & attribution

Licensed under **GPL-3.0-or-later** (see [LICENSE](LICENSE)). The AgX mode ports
portions of [darktable](https://github.com/darktable-org/darktable)'s GPL-3.0-or-later
AgX implementation, which is why the combined work is GPL. The Tony McMapface LUT is
an external asset dual-licensed Apache-2.0 OR MIT by
[h3r2tic/tony-mc-mapface](https://github.com/h3r2tic/tony-mc-mapface). See
[NOTICE.md](NOTICE.md) for details.
