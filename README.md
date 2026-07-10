# dngscan

**A small, offline RAW-to-JPEG laboratory built around darktable-derived AgX.**

[中文说明](README.zh-CN.md) · [License](LICENSE) · [Third-party notices](NOTICE.md)

`dngscan` reads a RAW file, inspects the capture signal, renders it through a
scene-linear Rec.2020 pipeline, and compresses it into an 8-bit sRGB or Display P3
JPEG. It is deliberately narrower than darktable: no catalog, layers, masks, local
retouching, or attempt to become a complete photo editor.

It is best understood as a **signal-processing tool, algorithm playground, and AgX
RAW compressor**.

## Why this exists

[darktable](https://github.com/darktable-org/darktable) is powerful and its scene-linear
pipeline is the foundation of this project, but it also has a broad editing model and a
real learning curve. I wanted a smaller instrument for one specific question:

> Given the optical signal recorded by a RAW capture, how should a fixed AgX image
> formation pipeline compress it into an ordinary JPEG without casually discarding
> highlight colour, shadow intent, or sensor evidence?

The AgX structure is the stable centre of dngscan. Automatic decisions are not meant to
"edit the photo for you". They are an attempt to respect the digitised optical signal:
measure black and white levels, per-channel clipping, usable shadow range, scene
distribution, and output-gamut pressure, then use those facts to compile conservative
curve parameters.

Exposure compensation, white balance, demosaic choice, camera-response correction, and
creative colour are controls around the AgX core. They remain explicit because they
express intent rather than a universal truth about the capture.

## What it is, and is not

| dngscan is | dngscan is not |
| --- | --- |
| An offline RAW analyser and converter | A Lightroom or darktable replacement |
| A focused darktable-derived AgX renderer | A local-retouching or masking tool |
| A repeatable experiment in RAW-aware compression | An automatic beauty grader |
| A place to compare tone and colour geometry | A claim of perfect camera colour science |

At `EV 0`, dngscan preserves the photographed brightness relationship. A night scene
stays dark. The optional **Brightness reference** button is a comparison tool that moves
the full-frame median toward 18% gray while respecting rendered highlight limits; it is
never applied silently.

## Pipeline

```text
RAW / DNG
  |
  +-- pre-demosaic CFA evidence
  |     black/white levels · per-channel clipping · headroom · noise confidence
  |
  +-- LibRaw
        demosaic · selected WB · camera interpretation
  |
scene-linear Rec.2020
  |
  +-- optional camera-response prefeed
  |
  +-- RenderPlan compiled from reliable scene body/tail and RAW evidence
  |
  +-- selected compression core
  |     AgX · RAW-gated AgX · luminance C1 control · generic control
  |
  +-- optional project-authored chromatic look
  |
Oklab gamut fit · sRGB/P3 encoding · 8-bit dither · JPEG
```

The important separation is between **evidence** and **appearance**. Reconstructed
highlights can look continuous, but they do not regain sensor headroom. dngscan keeps
the original CFA clipping evidence available after demosaic so reconstructed pixels do
not incorrectly define the global white endpoint.

## Compression cores

All finished modes use the same exposure anchor and delivery safeguards.

| GUI / CLI | Purpose | Expected result |
| --- | --- | --- |
| **AgX** / `agx` | Default darktable-style full-frame AgX with `smooth` primaries. RAW analysis compiles reliable C1 endpoints. | The most coherent path-to-white and the normal finished render. |
| **RAW gated** / `gated` | Uses the same darktable `smooth` candidate, but RAW evidence controls how much of its chromatic path is mixed per pixel. | A more conservative alternative when full-frame AgX changes too much colour. |
| **Scene C1, luminance only** / `lum` | Uses the same scene-derived C1 toe and shoulder but preserves RGB ratios. | Shows what AgX colour geometry adds beyond the tone curve. |
| **Generic curve** / `neutral` | Fixed non-AgX luminance shoulder with the same exposure anchor and delivery fit. | A conventional export reference, not a finished recommendation. |

The optional AgX geometry choices are comparison references, not different exposure
algorithms:

- `smooth`: darktable geometry and the default.
- `base`: Blender-style balanced reference.
- `punchy`: stronger colour recovery after the curve.
- `muted`: softer outward colour geometry.

## RAW-aware decisions

dngscan uses RAW analysis where it has factual authority:

- Per-channel black/white levels and clipping thresholds come from metadata plus the
  observed RAW distribution.
- CFA clip masks are collected before white balance and demosaic.
- Clipped or reconstructed samples are excluded from the reliable body statistics that
  compile the tone endpoints.
- Shadow limits use measured noise and camera priors instead of assuming every dark code
  is recoverable detail.
- Output-gamut pressure affects colour compression, not exposure or tone endpoints.

This is the project's main distinction from a stand-alone tone-mapping module: the
renderer can still consult capture evidence that is normally unavailable later in an
editor's pixel pipeline.

## Experimental camera prefeed

The idea I find most interesting is using sensor evidence before demosaic to inform a
later colour transform. dngscan already does this for CFA clipping and headroom. The
experimental **camera-response prefeed** itself currently runs after demosaic and camera
interpretation, in scene-linear Rec.2020, immediately before AgX.

The bundled skin/material prefeed is intentionally a rough prototype. It uses soft
chromaticity windows and constrained matrices derived from public, measured, digitised,
and analytic spectral inputs. It is **not** an official ARRI transform and not a strict
ALEXA/ALEV simulation.

Serious prefeed calibration would require controlled light sources, targets, spectral
measurements, and ideally calibration for each physical camera body, not merely each
model. I do not currently have that equipment. The existing ALEV-like geometry is here
as an honest experiment and an invitation for better measurements.

Calibration inputs and limitations are documented in
[`dngscan_assets/spectral/README.md`](dngscan_assets/spectral/README.md).

## Looks and LUTs

The public repository includes one project-authored warm-skin/cool-background chromatic
look because I like it. It is a small post-AgX Oklab field, not a vendor LUT.

The code also retains a local LUT adapter, making it easy to test legally obtained LUTs
around AgX. There is no universal answer to which creative LUT belongs after this DRT;
that is deliberately left open for experimentation. **No ARRI, Fujifilm, Sony, RED,
Resolve/Kodak, or other vendor LUT is distributed in this repository.** Please do not
submit vendor LUT files in issues or pull requests without explicit redistribution
permission.

## Quick start

Python 3.10 or newer is required.

```bash
git clone https://github.com/Gen-416/dngscan.git
cd dngscan
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m dngscan.gui
```

The GUI opens on localhost and works offline. It caches RAW decode/analysis and uses a
proxy for repeated previews; final export always returns to the full-resolution scene
buffer.

### Suggested GUI workflow

1. Select a RAW file and keep `EV 0` for the first preview.
2. Start with `AgX`, `darktable`, camera white balance, and `Keep clipping`.
3. Compare `RAW gated`, `Scene C1`, and `Generic curve` at the same EV when you want to
   understand where a visual difference comes from.
4. Try the prefeed only after the baseline render is understood.
5. Use **Brightness reference** only as an explicit alternate exposure reading.
6. Export sRGB for broad compatibility or Display P3 for a colour-managed P3 workflow.

### CLI examples

```bash
# Default full-frame AgX, quality 100, 4:4:4
python -m dngscan photo.dng --jpeg photo.jpg

# Add the six-panel RAW report
python -m dngscan photo.dng --jpeg photo.jpg --scan --csv photo.csv

# Compare tone cores at the same EV
python -m dngscan photo.dng --jpeg gated.jpg --tone-core gated
python -m dngscan photo.dng --jpeg lum.jpg --tone-core lum
python -m dngscan photo.dng --jpeg generic.jpg --tone-core neutral

# Try highlight reconstruction and Display P3
python -m dngscan photo.dng --jpeg photo_p3.jpg \
  --highlight-mode reconstruct --output-gamut p3

# Deliberately apply the full-frame brightness reference
python -m dngscan photo.dng --jpeg reference.jpg --ev auto
```

Run `python -m dngscan --help` for all options.

## Output and diagnostics

- SDR export is an 8-bit JPEG with deterministic TPDF dither. Defaults are quality 100
  and 4:4:4 chroma sampling.
- Display P3 output embeds a P3 ICC profile and fails rather than writing silently
  untagged P3 data.
- ISO gain-map HDR export exists as an experimental path and is not yet the recommended
  compatibility target.
- `--scan` writes a six-panel capture report: SNR versus stops, separate R/G/B RAW
  distributions, exposure and gamut pressure, and spatial clipping maps. Display curves
  may be smoothed; numerical statistics always use unsmoothed RAW samples.

## Contributing

This project is public so other people can play with the pipeline and challenge its
assumptions. Useful contributions include:

- camera measurements and reproducible calibration procedures;
- better RAW evidence models, highlight reconstruction, and noise confidence;
- AgX/DRT comparisons grounded in actual scenes;
- GUI clarity, cross-platform packaging, and colour-managed output tests;
- original or clearly redistributable looks and transforms.

Please keep the distinction between measured evidence, heuristic policy, and creative
taste explicit in code and documentation. Do not commit test RAW files or third-party
LUTs without permission.

## Licence and acknowledgements

dngscan is distributed under [GPL-3.0-or-later](LICENSE) because its AgX implementation
derives from darktable's GPL-3.0-or-later code. Open-source spectral data and optional
dependencies are listed in [NOTICE.md](NOTICE.md).

This is an independent community experiment. ARRI, ALEXA, ALEV, darktable, Blender,
Fujifilm, Sony, RED, Kodak, Resolve, and other names belong to their respective owners;
references describe compatibility, provenance, or comparison and do not imply
endorsement.
