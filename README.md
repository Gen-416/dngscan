# dngscan

A small offline tool that reads a RAW file and compresses it into a JPEG through AgX.
The AgX implementation comes from darktable's `agx` module.

[中文说明](README.zh-CN.md) · [License](LICENSE) · [Third-party notices](NOTICE.md)

dngscan reads a RAW file, measures the signal the sensor actually recorded, renders it
in scene-linear Rec.2020, and compresses it through AgX into an 8-bit sRGB or Display
P3 JPEG. Its responsibility ends there: no catalog, no layers, no masks, no local
retouching. **It is not a photo editor** — it is more precisely a signal-processing
tool: a developer, in the darkroom sense, whose single concern is compressing RAW
through AgX.

## Why it exists

My judgment of darktable is that it is, at its core, a signal-and-algorithm processing
instrument — a toy for signals, in the entirely respectful sense of an apparatus whose
pleasure lies in understanding and manipulating them. Its scene-referred pipeline is
rigorous and complete, but that completeness carries the full complexity of a general
editor. For the single task of compressing a RAW through AgX, most of that capability
is beside the point — and dngscan exists for exactly that reason. It takes this one
path out of the full editing system and makes it a standalone, reproducible,
deliberately small tool: LibRaw interpretation, scene-linear Rec.2020, and the curve
construction and primaries geometry ported from darktable's GPL `agx` module. Nothing
more.

Two positions run through the design.

**First, automatic decisions can only be justified by measurement.** The digitized
optical signal is the data this tool absolutely depends on: black and white levels,
per-channel CFA clipping, usable shadow range, the scene's luminance distribution — the
compression curve is compiled from these measurements. Automation here is respect for
the captured signal, not aesthetic decision-making on the user's behalf. A night scene
therefore stays dark at EV 0, and a lamp that clipped on the sensor does not acquire
the authority to define the image's white point merely because highlight reconstruction
rendered it smooth.

**Second, the imaging path must remain explainable.** The AgX compression pipeline
itself is deterministic; scene measurement compiles its working parameters, but taste
never enters the automatic analysis. Every control that expresses intent — exposure
compensation, white balance policy, the camera-response prefeed, chromatic looks, LUT
filters — stands outside the AgX core as an explicit option, off or neutral by default.
When the image changes, the cause can be named: the RAW itself, the DRT, or a choice
the user made.

## Pipeline

```text
RAW / DNG
  |
  +-- pre-demosaic CFA evidence
  |     black/white levels · per-channel clipping · headroom · noise confidence
  |
  +-- LibRaw: demosaic · selected WB · camera interpretation
  |
scene-linear Rec.2020
  |
  +-- optional camera-response prefeed          (outside the core)
  +-- RenderPlan compiled from reliable scene statistics and RAW evidence
  +-- compression core: agx · gated · lum · neutral
  +-- optional chromatic look / LUT filter      (outside the core)
  |
Oklab gamut fit · sRGB/P3 encode · 8-bit dither · JPEG
```

Reconstructed highlights can look continuous, but they never regain sensor headroom.
The CFA clipping evidence is collected before demosaicing and stays available to the
renderer, so reconstructed pixels cannot define the global white endpoint.

## Stage-by-stage choices

**Demosaic.** Full-resolution export defaults to `--demosaic auto`: Bayer sensors get
the best algorithm the current build supports in DHT → DCB → AHD order; non-Bayer
sensors (Fujifilm X-Trans) keep libraw's native path; previews use a fast half-size
path. Manual choices are `dht / dcb / ahd / aahd / vng / ppg`. One judgment matters
here: this tool performs no noise reduction, which makes demosaic the only texture
lever. DHT resolves the most detail on clean low-ISO signal; on noise-heavy high-ISO
files, detail-aggressive interpolation amplifies chroma noise into maze patterns and
false color — the smoother `vng` and `ppg`, or the false-color-suppressing `dcb` and
`aahd`, often read better there. Noisy night captures are worth one manual algorithm
comparison.

**White balance.** `camera` uses the in-camera AsShot multipliers; `daylight` uses
libraw's calibrated daylight multipliers for film-style roll consistency — every frame
under the same light gets the same balance, and color casts remain as properties of the
scene. Either way, the AsShot deviation from daylight is always reported as testimony
about the light source.

**Highlights.** Three libraw strategies: `clip / blend / reconstruct`. The choice
affects visual continuity only, never evidence: the CFA clipping state is captured
before demosaicing, and reconstructed pixels can never feed back into the curve
endpoints.

**Output and gamut.** SDR is an 8-bit JPEG, default quality 100 with 4:4:4 chroma
(4:2:2 / 4:2:0 available), with deterministic TPDF dither applied before quantization
to avoid banding in smooth gradients. `--output-gamut srgb` targets maximum
compatibility; `p3` embeds a Display P3 ICC profile and fails loudly rather than
writing untagged wide-gamut data. `--output-format ultrahdr` writes an ISO gain-map
HDR JPEG and remains experimental.

**Exposure.** The anchor is a content-independent constant: nominally exposed mid gray
maps to scene-linear 0.18, and `--ev` offsets from there. `--ev auto` is an explicit
brightness reference — median aligned to 18% gray, bounded by a highlight growth
budget — a reading you choose deliberately, never applied silently.

## Compression cores

All four cores share the same exposure anchor and delivery safeguards, so an A/B
between them isolates exactly one variable.

| core | what it does |
| --- | --- |
| `agx` | Full-frame darktable-style AgX with `smooth` primaries; the finished default. |
| `gated` | Same AgX candidate, but RAW evidence decides per pixel how much of its chromatic path applies. More conservative. |
| `lum` | The same scene-compiled C1 toe/shoulder applied to luminance only, RGB ratios preserved. Shows what AgX color geometry adds. |
| `neutral` | A fixed generic shoulder, no AgX at all. A conventional-export reference, not a recommendation. |

The `--agx-primaries` presets (`smooth` default, `base`, `punchy`, `muted`) change only
the AgX inset/outset geometry — comparison references, not different exposure
algorithms.

## Camera-response prefeed (experimental)

"Prefeed" here means correcting a camera's systematic colorimetric error in the
scene-linear domain, before the image formation — not applying a style after it. The
premise is that a camera's color is determined by its spectral sensitivity functions
(SSF) and filter-stack transmission, which are measurable, physically stable properties
of an individual body. The first-order goal follows directly: if the deviation is
known, compensate it digitally before the DRT has to compress it. The generalization
is the second: given two sufficiently well-measured responses, the same operator can
map part of camera A's response relationships toward camera B or a different
CMOS/filter stack. This has a hard physical boundary — no per-pixel operator can
recover spectral information the sensor never recorded, so two materials that are
metameric under A cannot be given the distinction they would have shown under B. What
remains feasible is approximating response relationships per material class, with an
error figure and a confidence attached to each class.

The current implementation is built to that boundary. For five material classes —
skin, foliage, cyan, neutral, magenta — constrained per-class 3×3 mappings are fitted
on synthesized responses (SSF × illuminant × reflectance). At runtime each mapping's
domain of validity is bounded by a soft Gaussian window in the (R/G, B/G) chromaticity
plane, transported across white balance via von Kries scaling; per-class residuals and
cross-class leakage are recorded in a calibration report, and each class's confidence
is folded into its effective strength. All inputs are public: the ALEV III SSF is
digitized from Leonhardt & Brendel (CIC23) — ARRI averaged measurements of five ALEXA
bodies because the sensor stack's interference ripple is unit-specific, which is also
why serious prefeed calibration must target the individual body, not the model; the
Sigma fp side uses the Sony A7 III full-camera SSF measured by Weta Digital (AMPAS
rawtoaces-data; same IMX410 sensor); camera→Rec.2020 profiles are fitted on the AMPAS
190 training reflectances. One distinction matters: CFA clipping and headroom evidence
is collected before demosaicing and feeds the tone plan and the gated core; the color
prefeed itself operates after demosaicing and camera interpretation, immediately
before AgX.

Choosing ARRI as the mapping target is personal: I want the skin I see in ARRI
footage — a warmth carried by blood color, set against a cooler cyan field. I suspect
this owes something to the ALEV stack's comparatively permissive red/near-IR passband,
and this project's own calibration report points the same way: of the five material
classes, the largest native divergence is foliage, the class that depends on red-edge
response. But this is a goal, not an achievement. I own no controlled illuminants,
reference targets or spectral measurement equipment; the shipped mapping is a
geometric approximation built from digitized public curves and analytic spectra, and
it behaves like a restrained color mapping rather than an ARRI skin response. Errors,
confidences and data provenance are documented in
`dngscan_assets/spectral/README.md`.

## Looks and LUT slots

One project-authored look ships — `optic_warm_cyan`, warm skin against a cooler field —
because I like it; it is a by-product of the ARRI-look work above. It is a small
post-AgX Oklab field written for this repository, not a vendor LUT.

The LUT filter adapter stays, with three documented slots (Kodak 2383 print emulation,
RED IPP2, Sony LC-709TypeA). Place a legally obtained `.cube` at the expected path
under `dngscan_assets/vendor_luts/` (exact paths are in `dngscan/display_filter.py`)
and the filter appears in the CLI and GUI automatically; remove the file and it
disappears. I honestly do not know which LUT truly "belongs" after an AgX DRT — that question is
left to everyone; I hope it produces good new ideas. **No vendor LUT is distributed in this repository**,
and please do not attach vendor LUT files to issues or pull requests without explicit
redistribution permission.

## Quick start

Python 3.10 or newer.

```bash
git clone https://github.com/Gen-416/dngscan.git
cd dngscan
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m dngscan.gui
```

The GUI runs on localhost, fully offline. Decode and analysis are cached per file;
previews use a proxy, and export always renders from the full-resolution scene buffer.
A reasonable first session: open a RAW at EV 0 with the default AgX core, look at the
render, then switch cores at the same EV when you want to know where a visual
difference comes from. The brightness-reference button (`--ev auto`) is an explicit
alternate exposure reading — it is never applied silently.

### CLI examples

```bash
# Default full-frame AgX, quality 100, 4:4:4
python -m dngscan photo.dng --jpeg photo.jpg

# Add the six-panel RAW report
python -m dngscan photo.dng --jpeg photo.jpg --scan --csv photo.csv

# Compare cores at the same EV
python -m dngscan photo.dng --jpeg gated.jpg --tone-core gated
python -m dngscan photo.dng --jpeg lum.jpg   --tone-core lum
python -m dngscan photo.dng --jpeg plain.jpg --tone-core neutral

# Highlight reconstruction, Display P3
python -m dngscan photo.dng --jpeg photo_p3.jpg --highlight-mode reconstruct --output-gamut p3

# Deliberately apply the brightness reference
python -m dngscan photo.dng --jpeg reference.jpg --ev auto
```

`python -m dngscan --help` lists everything.

## Output and diagnostics

SDR export is an 8-bit JPEG with deterministic TPDF dither (default quality 100,
4:4:4). Display P3 embeds the ICC profile and fails loudly rather than writing untagged
P3. The ISO gain-map HDR path exists but is experimental. `--scan` writes a six-panel
capture report — SNR versus stops, separate R/G/B RAW distributions, exposure and gamut
pressure, spatial clipping maps; plotted curves may be smoothed, numerical statistics
never are.

## Contributing

The project is public so people can play with AgX and push it somewhere new. Camera measurements, better RAW evidence models, grounded AgX/DRT
comparisons, and original or clearly redistributable looks are all welcome. Keep the
line between measured evidence, heuristic policy and creative taste explicit, and do
not commit RAW test files or third-party LUTs without permission.

## License and acknowledgements

dngscan is GPL-3.0-or-later because its AgX implementation derives from darktable's
GPL code; see [NOTICE.md](NOTICE.md) for spectral data sources and optional
dependencies. AgX itself originates with Troy Sobotka and matured in the Blender /
EaryChow ecosystem; this project inherits it through darktable's `agx` module. This is
an independent experiment: ARRI, ALEXA, ALEV, darktable, Blender, Fujifilm, Sony, RED,
Kodak, Resolve and other names belong to their owners, and are referenced only for
provenance and comparison.
