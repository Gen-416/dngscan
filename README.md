# dngscan

A small offline tool that compresses RAW files into JPEGs through AgX — the tone
reproduction ported from darktable's `agx` module.

[中文说明](README.zh-CN.md) · [License](LICENSE) · [Third-party notices](NOTICE.md)

dngscan reads a RAW file, measures what the sensor actually recorded, renders it in
scene-linear Rec.2020, and compresses it into an 8-bit sRGB or Display P3 JPEG. That is
the whole job. There is no catalog, no layers, no masks, no local retouching — this is
not a photo editor, and it is not trying to become one.

## Where it comes from

I like darktable. Its scene-referred pipeline is, at heart, a signal-processing
laboratory, and that is exactly why it is hard to recommend casually: the learning
curve is real, and the same image can be reached through a dozen interacting modules.
dngscan takes one opinionated path out of that laboratory and freezes it: LibRaw
interpretation, scene-linear Rec.2020, and an AgX image formation whose curve
construction and primaries geometry are ported from darktable's GPL `agx` module. AgX
itself originates with Troy Sobotka and matured in the Blender / EaryChow ecosystem;
this project inherits through darktable rather than reinventing.

Two convictions shape the design.

**Automatic decisions are respect for the digitized optical signal, not a robot
retoucher.** The tool measures black and white levels, per-channel CFA clipping, usable
shadow range and the scene's luminance distribution, and compiles the compression curve
from those measurements. A night scene stays dark at EV 0. A lamp that clipped on the
sensor is not allowed to redefine the image's white point merely because highlight
reconstruction painted it smooth.

**The compression pipeline itself is fixed.** What adapts inside it is compiled from
measurement, never from taste. Everything that does express taste — exposure
compensation, white balance policy, the camera prefeed, chromatic looks, LUT filters —
sits explicitly outside the AgX core, before or after it, and defaults to off or
neutral.

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

## The camera prefeed (experimental)

The idea I care most about is letting information taken from the sensor *before*
demosaicing inform the color transform that runs afterwards. dngscan already does this
rigorously for CFA clipping and headroom: collected pre-demosaic, consulted by the tone
plan and the gated core. The experimental camera-response prefeed — a soft
chromaticity-windowed mapping toward an ALEV-like response — runs later, in
scene-linear Rec.2020 immediately before AgX.

I want to be straight about its status: it is not a serious calibration. Serious
prefeed design needs controlled illuminants, reference targets and spectral
measurement, and really needs doing per physical camera body rather than per model —
when ARRI published the ALEXA's spectral sensitivities they averaged five cameras,
precisely because the sensor stack's interference ripple differs unit to unit. I do not
own that equipment. What ships is a geometric mapping built from digitized public
curves and analytic spectra, with its error report and per-material confidence weights
in the open (`dngscan_assets/spectral/README.md`). Treat it as an invitation, not a
claim.

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
dependencies. This is an independent experiment: ARRI, ALEXA, ALEV, darktable, Blender,
Fujifilm, Sony, RED, Kodak, Resolve and other names belong to their owners, and are
referenced only for provenance and comparison.
