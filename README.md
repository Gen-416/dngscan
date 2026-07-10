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
editor: modules interact, the same image can be reached along many paths, and the
learning cost falls on everyone who only wants one RAW developed correctly. For the
single task of compressing a RAW through AgX, most of that capability is beside the
point — and dngscan exists for exactly that reason. It takes this one path out of the
full editing system and makes it a standalone, reproducible, deliberately small tool:
LibRaw interpretation, scene-linear Rec.2020, and the curve construction and primaries
geometry ported from darktable's GPL `agx` module. It does not compete with darktable,
and it does not reinvent AgX.

Two positions run through the design.

**First, automatic decisions can only be justified by measurement.** The digitized
optical signal is the only source of fact this tool recognizes: black and white levels,
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

## What I mean by camera prefeed (experimental)

By "prefeed" I do not mean another look filter. The first goal is practical: use known
sensor and filter-stack behaviour to compensate recurring colour errors before the DRT
has to compress them. If that response is measured well enough, the same machinery can
also map part of one camera's response toward another camera or CMOS/filter stack. It
cannot recreate spectral information that was never captured, but it may reproduce
some of the colour relationships that give a camera its character.

The specific experiment here started with the Sigma fp. I wanted to see whether its
response could be nudged toward the skin quality I associate with ARRI cameras: a
warmer, blood-rich skin response set against a slightly cooler cyan field, which I
suspect is partly related to the ARRI sensor and its comparatively permissive red / IR
filter stack. That is the intention, not the achievement. The current result is still
less convincing than I hoped; it behaves more like a cautious geometric colour mapping
than the skin response of an ARRI camera.

dngscan does collect CFA clipping and headroom before demosaicing and carries that
evidence into the later render. The colour prefeed itself currently runs after
demosaicing and camera interpretation, in scene-linear Rec.2020 immediately before
AgX. A serious version would need controlled illuminants, reference targets and
spectral measurements, ideally for each physical camera body rather than only each
model. I do not own that equipment. What ships is a rough ALEV-like mapping built from
digitised public curves and analytic spectra, with its errors and confidence values
documented in `dngscan_assets/spectral/README.md`. It is a starting point, not a claim
of ARRI colour science.

## Looks and LUT slots

One project-authored look ships — `optic_warm_cyan`, warm skin against a cooler field —
because I like it. It is a small post-AgX Oklab field written for this repository, not
a vendor LUT.

The LUT filter adapter stays, with three documented slots (Kodak 2383 print emulation,
RED IPP2, Sony LC-709TypeA). Place a legally obtained `.cube` at the expected path
under `dngscan_assets/vendor_luts/` (exact paths are in `dngscan/display_filter.py`)
and the filter appears in the CLI and GUI automatically; remove the file and it
disappears. I honestly do not know which creative LUT "belongs" after an AgX DRT — that
question is left open on purpose. **No vendor LUT is distributed in this repository**,
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

The project is public so people can play with the pipeline and challenge its
assumptions. Camera measurements, better RAW evidence models, grounded AgX/DRT
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
