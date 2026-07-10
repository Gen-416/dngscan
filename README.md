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

Every option visible in the GUI corresponds to a real stage of the pipeline; this
section explains, in order, what each one actually does.

**Demosaic.** Full-resolution export defaults to `--demosaic auto`: Bayer sensors get
the best algorithm the current build supports in DHT → DCB → AHD order; non-Bayer
sensors (Fujifilm X-Trans) keep libraw's native path. Previews bypass interpolation
entirely and use half-size superpixel binning (each 2×2 cell collapses to one pixel),
so preview texture says nothing about interpolation quality. Manual choices are
`dht / dcb / ahd / aahd / vng / ppg`. One judgment matters here: this tool performs no
noise reduction, which makes demosaic the only texture lever. DHT resolves the most
detail on clean low-ISO signal; on noise-heavy high-ISO files, detail-aggressive
interpolation amplifies chroma noise into maze patterns and false color — the smoother
`vng` and `ppg`, or the false-color-suppressing `dcb` and `aahd`, often read better
there. Noisy night captures are worth one manual comparison. Worth knowing: libraw
itself defines more algorithms — LMMSE (the classic choice designed for noise-heavy
captures), AMaZE, VCD, AFD — which come from the GPL demosaic packs and are absent
from standard rawpy wheel builds. If your libraw build carries them, exposing one is a
one-line addition to `DEMOSAIC_CHOICES`: the resolver already checks availability and
falls back gracefully.

**White balance.** `camera` uses the in-camera AsShot measurement; `daylight` uses
libraw's calibrated daylight multipliers for film-style roll consistency — every frame
under the same light gets the same balance, and color casts remain as properties of the
scene. Either way, the AsShot deviation from daylight is reported as testimony about
the light source. The position here is, again, to trust measurement: as long as the
illuminant belongs to the daylight family (sun, overcast, shade), the estimation
problem lives on the roughly one-dimensional blackbody–daylight locus and is
well-conditioned — the in-camera measurement is usually accurate enough, whereas the
eye judging a display is already chromatically adapted to that display's white point
and the room, which makes eyeballing white balance a circular reference. The limits of
the measurement deserve equal honesty: mixed sources, narrow-band artificial light
(LED, fluorescent, sodium vapor) and frames dominated by a single color degrade the
estimate into an ill-posed problem. And one layer further, often overlooked: much of
what is perceived as "wrong white balance" is not white balance at all — color
appearance effects (Hunt, Stevens, Abney, Bezold–Brücke) mean that a tone curve's
redistribution of luminance and purity itself shifts perceived hue and warmth, and
memory colors (skin, sky, foliage) were never colorimetrically correct expectations to
begin with. Before touching WB, confirm the deviation is not coming from the tone and
chroma layers.

**Highlights.** The three libraw strategies differ in mechanism. `clip` cuts hard at
sensor saturation — the most honest, but the three channels clip at different levels,
so highlight borders often carry magenta or cyan fringes; `blend` feathers the
transition; `reconstruct` estimates the clipped channels from the surviving ones —
plausible luminance structure, but the chroma is an estimate that drifts toward the
surviving channel's hue. The choice affects visual continuity only, never evidence:
the CFA clipping state is captured before demosaicing, reconstructed pixels can never
feed back into the curve endpoints, and the clip classes are exactly what the `gated`
core consumes. In practice: use reconstruct where highlight gradients matter (lamps,
backlit sky), and clip where maximum honesty matters (calibration, measurement).

**Purity compensation (punch).** The mechanism behind AgX-family flatness is described
in the section above; punch is a scene-gated correction for it, not a style layer. The
gate is a product of three scalars — subject brightness (median near mid gray), sensor
quality (usable DR from camera priors or single-frame measurement), and window width —
so bright, low-ISO, wide-window scenes receive an Oklab chroma lift automatically,
while night and high-ISO scenes gate to exactly zero and short-circuit the operator:
their renders are byte-identical. Every weight multiplies into the gain's increment,
so the gain is ≥ 1 everywhere (it never desaturates) and attenuates on the neutral
axis (grays immune), in deep shadows (no noise amplification), in highlights
(preserving the path-to-white), on already-rich colors (a knee caps them) and in the
skin band (halved). Its limits deserve stating too: this is a global chroma policy
driven by scalar scene statistics, with thresholds tuned on a limited corpus. The
slider is a multiplier on the automatic value: 1 uses the analyzed value, 0 disables.

**Output and gamut.** SDR is an 8-bit JPEG, default quality 100 with 4:4:4 chroma
(4:2:2 / 4:2:0 available), with deterministic TPDF dither applied before quantization
to avoid banding in smooth gradients. `--output-gamut srgb` targets maximum
compatibility; `p3` embeds a Display P3 ICC profile and fails loudly rather than
writing untagged wide-gamut data. `--output-format ultrahdr` writes an ISO gain-map
HDR JPEG, with `--hdr-headroom` setting the gain-map ceiling in EV; this path remains
experimental.

**Exposure.** The anchor is a content-independent constant: nominally exposed mid gray
maps to scene-linear 0.18, shared by all four cores, so EV means the same thing in any
scene under any core, and `--ev` offsets from there. This is a deliberate rejection of
content-adaptive exposure — a night scene staying dark at EV 0 is design, not defect;
for sufficiently clean dark scenes the tool applies a display-side interior brightness
lift (view brightness, true black and white point untouched) instead of raising
exposure. `--ev auto` is an explicit brightness reference: it aligns the frame median
to 18% gray, bounded by a highlight growth budget — light sources already clipped on
the sensor do not count against the budget (lamps are supposed to clip), only newly
created clipping limits the boost. Its limitation follows from its mechanism: the
median is a global statistic, so a backlit subject whose median is dominated by the
background still needs manual EV — which is what the slider is for.

## AgX formation and the compression cores

First, what AgX itself is. A per-channel sigmoid is the shared skeleton of every
film-like digital formation: R, G and B each pass through the same S-curve, so
highlights roll off and shadows compress naturally. But a bare per-channel curve has a
famous side effect — the three channels saturate at different rates, so hue drifts with
brightness (the "notorious six": pure red slides toward orange-yellow in highlights,
pure blue toward cyan). AgX's contribution is a pair of matrices around the curve. The
**inset**, before the curve, contracts the working primaries toward the achromatic axis
with a small rotation: the contraction guarantees no color enters the curve at extreme
purity, giving bright saturated colors a smooth path-to-white instead of congealing
into neon patches at the channel ceiling; the rotation pre-compensates perceptual hue
shifts such as Abney. The **outset**, after the curve, restores purity — deliberately
not the inverse of the inset, and the difference between the two is precisely AgX's
character. The curve itself uses darktable's C1 piecewise construction (toe, linear
segment, shoulder, continuous in both value and slope at the joins); its endpoints are
compiled from scene statistics, and calibrated EV 0 always maps to 18% output.

AgX's inherent limits deserve equal clarity, because they motivate several of this
tool's later designs. First, the inset's up-front desaturation is only earned back by
content deep in the toe, through per-channel expansion — which is why high-ISO night
frames look rich while daylight wide-DR scenes run inherently flat (that the Blender
ecosystem never ships AgX Base without a Punchy look is the same fact stated
differently); purity compensation (punch) exists for exactly this. Second, chromatic
behavior is coupled to where content lands on the curve: the same object can render
with different saturation in different framings or exposures. That is the structural
price of delegating color decisions to per-channel curves — and the reason the `gated`
and `lum` control paths exist.

All four cores share the same exposure anchor and delivery safeguards, so an A/B
between them isolates exactly one variable.

| core | what it does |
| --- | --- |
| `agx` | Full-frame darktable-style AgX with `smooth` primaries; the finished default. |
| `gated` | Same AgX candidate, but RAW evidence decides per pixel how much of its chromatic path applies. More conservative. |
| `lum` | The same scene-compiled C1 toe/shoulder applied to luminance only, RGB ratios preserved. Shows what AgX color geometry adds. |
| `neutral` | A fixed generic shoulder, no AgX at all. A conventional-export reference, not a recommendation. |

`gated` deserves one more sentence of mechanism: it renders both the lum luminance
result and the AgX color result, re-normalizes the AgX output to the same Rec.2020
luminance as lum, and then lets RAW evidence (clip class, remaining headroom, noise
confidence) decide the per-pixel mix — there is exactly one luminance authority, so a
confidence boundary can never produce a brightness seam. `neutral`'s curve endpoints
are fixed constants rather than scene-compiled; the question it answers is "roughly
what would an ordinary converter produce".

When `lum` is selected, the norm option decides which scalar the curve acts on, and
this is a trade with no single right answer: `y` (Rec.2020 luminance) is
colorimetrically strictest, but a saturated color's loudest channel can overshoot the
display ceiling and needs the display-side chroma retreat as a backstop; `max` drives
the curve with the loudest channel, so saturated colors never overshoot — at the cost
of darkening every saturated color relative to its luminance, the flattest rendering;
`power` (fourth-power weighting) is the compromise. Ratio preservation means hue and
saturation are carried through tone exactly — which also means bright saturated
highlights read "neon". That is the known failure mode of chromaticity-preserving tone
mapping, and precisely the reason the per-channel AgX route is the default.

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

The GUI runs on localhost, fully offline. Selecting a file silently warms a proxy scene
and its basic analysis; that proxy stays in memory and is also kept in the local user cache,
so reopening the same file after a restart can reuse it. On macOS the default location is
`~/Library/Caches/dngscan/preview-v1`; it is bounded to 768 MB and evicts old entries automatically.
Deleting it only means the next preview will warm again: it never changes a RAW or an export.
Previews use the proxy, while export always renders from the full-resolution scene buffer in a
short-lived worker process, so its large arrays return to the OS when it finishes. A reasonable
first session: open a RAW at EV 0 with the default AgX core, look at the
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
