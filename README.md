# dngscan

[中文说明](README.zh-CN.md)

`dngscan` is a local, offline RAW analyser and JPEG renderer. It treats the RAW
file as capture evidence, not merely as pixels to be pushed through a display curve:
per-channel CFA headroom, clipping, noise confidence, reliable scene luminance, and
output-gamut pressure are measured before a scene-linear Rec.2020 render is compiled
into an SDR JPEG.

It is deliberately not a general-purpose RAW editor. Its job is to make a small set of
rendering decisions explicit and repeatable: preserve the photographed exposure intent,
reserve the shoulder for measured headroom, and only change highlight colour where the
capture or delivery constraints justify it.

## Core idea

The default renderer is **AgX: darktable global colour path** with darktable's `smooth`
primary geometry. RAW analysis is still structural: it compiles the C1 toe/shoulder,
protects the white endpoint from clipped/reconstructed samples, informs output-gamut
fitting, and reports the capture's limits. It does not turn the default into a
Blender-oriented image pipeline.

**Fidelity: RAW evidence driven** is a separate, optional strategy. It uses the same
darktable smooth AgX geometry as the candidate colour path, but blends that path only
where RAW evidence, scene brightness, SNR, gamut pressure, and hue policy permit it.
This separation matters when comparing a reconstructed lamp with a well-exposed skin
tone: the lamp cannot set the global white endpoint, and the skin need not lose chroma
because another part of the frame clipped.

```text
RAW / DNG
  |
  +-- CFA evidence: per-channel black/white, clip class, headroom, SNR
  |
  +-- LibRaw decode: demosaic, WB, camera matrix -> scene-linear Rec.2020
                                                    |
                                                    +-- optional camera-response correction
                                                    |
reliable scene body/tail ---------------------------+-- RenderPlan
                                                         | tone: C1 endpoints, toe, shoulder
                                                         | colour: RAW/gamut permissions
                                                         v
                                                selected compression strategy
                                                         |
                                 optional look or output LUT (one, never both)
                                                         |
                                      Oklab gamut fit -> sRGB/P3 encode -> dither -> JPEG
```

The analyser and renderer use the same highlight mode and scene buffer. CFA-domain
facts remain independent of demosaic or reconstruction, so the tool can distinguish
"the renderer made this highlight look continuous" from "the sensor still clipped this
channel".

## Exposure and the full-frame reference

For the three tone-mapped strategies, a fixed camera-independent scalar places nominal
scene middle gray at 18% before the curve. It is not computed from image content. At
`EV 0`, a night scene therefore remains a night scene; the tone plan may shape its toe
and shoulder, but it does not convert a dark capture into gray daylight.

`EV` is a manual offset around that anchor. The GUI's **Full-frame brightness reference**
button, and CLI `--ev auto`, are optional reference operations: they measure the
full-frame median, calculate the EV that would place it at 18%, and cap upward
movement using the rendered highlight safety limit. They are useful for an accidentally
underexposed ordinary scene or as a comparison point. They are not an assertion of
photographic intent and are never applied unless explicitly invoked.

## Compression strategies

All non-neutral strategies compile black and white endpoints from the reliable
scene-luminance distribution. The black side is bounded by the usable DR/noise estimate;
the white side is based on the *reliable* tail, not CFA-clipped or reconstructed samples.
All use the same C1-continuous toe/shoulder family and the same fixed 18% pivot. What
changes is the authority used for colour.

| GUI name / CLI core | What the renderer does | Expected image | Best use |
| --- | --- | --- | --- |
| **AgX: darktable global colour path** / `agx` | Applies AgX inset -> log2 C1 curve -> hue mix -> outset to every pixel, followed by the scene-driven purity operator. The default path is darktable `smooth`. | The most recognisably global AgX behaviour: chromatic highlights follow a coherent AgX path, while RAW analysis still sets reliable tone endpoints. | Default finished render. |
| **Fidelity: RAW evidence driven** / `gated` | Maps Rec.2020 luminance through the C1 curve everywhere. It computes a darktable-`smooth` AgX result, rescales it back to the same Rec.2020 Y, then blends only its chroma/path-to-white by a per-pixel permission weight. | A local, evidence-driven colour path with no RAW-mask brightness seam. It is not a promise of higher saturation than full AgX. | A RAW-aware alternative when the global AgX colour path is too broad for the scene. |
| **Luminance priority** / `lum` | Reduces a scalar norm through the C1 curve and multiplies RGB by the resulting ratio. Apart from known clipped samples and final delivery guards, RGB ratios are retained. | The closest tone-mapped option to scene RGB proportions. Saturated highlights can remain more literal and less filmic; colour separation comes from the capture rather than an AgX hue path. | Inspecting whether AgX geometry is helping a scene, or preserving product/graphic colours. |
| **Linear reference** / `neutral` | Skips the tone core. Scene-linear Rec.2020 is converted only for delivery, then gamut-fitted and encoded. | No designed shoulder or toe. Bright values reach delivery limits directly, so this is a diagnostic reference, not a finished JPEG look. | A/B analysis, checking the cost of any DRT. |

For `gated`, the colour permission is continuous, not a binary "clipped/not clipped"
mask. It rises with measured per-channel headroom loss and multi-channel clipping; it
can also open in the bright shoulder, under delivery-gamut pressure, and where colour
SNR is trustworthy. It is reduced for trustworthy skin midtones, while bright green/cyan
can open slightly more. The raw-loss signal always has priority over this aesthetic hue
policy.

`lum` offers three scalar norms: `y` is Rec.2020 luminance and is the normal choice;
`power` gives strong individual channels more influence; `max` follows the brightest
channel and is the most highlight-protective but can look flatter. These are diagnostic
choices, not three different exposure anchors.

## AgX highlight paths

The **AgX highlight path** selector applies to `agx` only. `gated` always uses
darktable `smooth` geometry before its RAW permission blend. The selector does **not**
choose a different shoulder curve, white point, exposure, or dynamic-range plan. All
four paths share the same scene-derived C1 curve; they change the geometric AgX
formation around that curve:

```text
Rec.2020 RGB -> inset / primary rotation -> per-channel C1 curve -> hue mix -> outset
```

The inset deliberately mixes and contracts primaries before the curve, so a saturated
highlight does not behave like three unrelated channel clips. The outset decides how
much colour geometry is recovered after the curve. This is why the selector changes the
*route to white*, not the brightness roll-off.

| Path | Underlying geometry | Expected highlight behaviour |
| --- | --- | --- |
| **darktable smooth** / `smooth` | darktable's smooth-primary construction: different inset/outset distances and rotations, not a different sigmoid. | Default. A distinct, generally calmer hue trajectory through saturated highlights. It is the baseline for dngscan's full-frame AgX and RAW-gated paths. |
| **Blender reference: balanced retreat** / `base` | Blender-like / darktable blender-like Rec.2020 primary construction, with Blender's 0.4 hue-mix anchor. | A reference alternative to smooth: bright saturated colours soften and move toward white without strong colour recovery. |
| **Blender reference: vivid** / `punchy` | Same inset as `base`, but its outward-primary recovery is reduced in the geometric construction (`master_outset_ratio=0.5`). This restores more apparent purity after the curve. | More coloured high lights and stronger local colour separation. It can be attractive for neon, foliage, or coloured light, but extreme sRGB/P3 values may later be reduced by gamut fitting. |
| **Blender reference: soft** / `muted` | Same base inset, with the outward primary rotation also restored (`master_unrotation_ratio=1`). The tone curve is unchanged; only the outward colour geometry differs. | A calmer, less assertive bright-colour recovery than `base`. It can appear to retreat to neutral sooner, even though the luminance shoulder starts at the same place. |

The separate **Midtone purity** control is not one of these four paths. It is a
scene-gated post-core chroma operator used only by `gated` and `agx`; its automatic
strength goes to zero for unsuitable dark/high-ISO scenes. It never changes exposure,
toe, shoulder, or the white endpoint.

## RAW restoration choices

These settings happen before the tone core and have a larger factual effect than a
creative look.

| Setting | Meaning | Trade-off |
| --- | --- | --- |
| **Keep clipping** / `clip` | LibRaw leaves clipped highlights clipped. | No invented colour; the clearest reference for sensor loss. |
| **Highlight blend** / `blend` | LibRaw blends information from surviving channels. | Can retain colour in single-channel clips; may be less literal at severe clips. |
| **Highlight reconstruction** / `reconstruct` | LibRaw's neighbourhood-based highlight reconstruction. | Often smoother and more coloured highlights, but some result is an estimate. RAW clip evidence remains available to the gated renderer. |
| **Camera WB** / `camera` | Uses the camera's As Shot white balance. | Closest to the capture metadata. |
| **Fixed daylight** / `daylight` | Uses LibRaw's calibrated daylight multipliers. | A repeatable baseline across a series; not a claim that the scene was daylight. |
| **Demosaic auto** / `auto` | Full-resolution Bayer export prefers DHT, then DCB/AHD; non-Bayer formats use LibRaw's native path. | Detail reconstruction only. dngscan does not apply denoise. |

## Other colour and delivery layers

**Camera response correction** is an experimental, pre-core scene-linear transform. The
built-in ARRI-like and ALEV material presets use constrained matrices inside soft
chromaticity windows. They preserve the neutral axis and do not act as a display LUT.
Their spectral inputs are replaceable bootstrap/calibration data, not a claim of a
strict ALEXA emulation. Leave this layer off for a neutral baseline.

**Finished look** is optional and comes after the tone core. A chromatic LookField
changes Oklab hue/chroma while keeping lightness unchanged. A display LUT is a complete
log-in/display-out transform and can change tone as well as colour. The two paths are
mutually exclusive. Vendor LUT files are intentionally not included in the repository;
use only copies you are permitted to install locally.

**Delivery gamut** is a separate constraint. Scene rendering remains Rec.2020 until the
end. Out-of-gamut output is fitted in Oklab by reducing chroma while preserving hue as
far as possible, rather than by independently clipping RGB channels. `sRGB` is the
compatibility choice. `Display P3` embeds a P3 ICC profile and fails rather than silently
writing untagged P3 data when a profile cannot be found. JPEG defaults to quality 100 and
4:4:4 chroma sampling.

The ISO gain-map HDR path is present as an **experimental** output path. It is not part
of the recommended stable delivery workflow until cross-platform behaviour is verified.
The normal SDR JPEG is the supported default.

## Diagnostics

`--scan` writes the six-panel diagnostic PNG. It is a capture report, not a beauty score.

- **SNR vs stops**: use it to judge shadow recovery latitude. Around SNR 32 is visually
  clean, around 10 is usually usable with visible cost, and near 1 signal is overwhelmed
  by noise. It is not an instruction to raise all shadows to a fixed level.
- **R/G/B raw distributions**: use stops from clip on the horizontal axis. Separate
  panels avoid channel overlap; the red band marks the clip region. Statistics use
  unsmoothed RAW data even when the plotted density is smoothed.
- **RGB exposure distribution and gamut pressure**: show how much delivery colour work
  is likely after the DRT. They do not move the C1 tone endpoints.
- **Spatial exposure and clipped-channel maps**: identify whether the tail is a small
  light source, broad clipped subject detail, or a single-channel problem.

## Install and use

Python 3.10+ is required.

```bash
pip install -r requirements.txt
python -m dngscan.gui
```

The GUI is local and opens a localhost page. It caches the decode/analysis for a file,
uses a proxy for repeat previews, and always uses the full-resolution buffer for export.
The practical workflow is:

1. Start from `AgX: darktable global colour path`, `darktable smooth`, `EV 0`, and a chosen RAW
   highlight mode.
2. Use **Full-frame brightness reference** only as a deliberate comparison; return to
   `EV 0` when the photographed low-key/high-key intent is correct.
3. Compare `gated`, `agx`, and `lum` before adding a camera correction or finished look.
4. Use the full-resolution export metrics, not only proxy-preview white percentages,
   when deciding how far to raise manual EV.
5. Export sRGB for broad delivery or P3 for colour-managed P3 viewers.

CLI examples:

```bash
# Finished SDR JPEG: default darktable-style full-frame AgX, quality 100, 4:4:4
python -m dngscan photo.dng --jpeg photo.jpg

# Full capture report plus JPEG
python -m dngscan photo.dng --jpeg photo.jpg --scan --csv photo.csv

# Compare the default and two meaningful DRT alternatives at the same EV
python -m dngscan photo.dng --jpeg agx.jpg --tone-core agx --agx-primaries smooth
python -m dngscan photo.dng --jpeg gated.jpg --tone-core gated
python -m dngscan photo.dng --jpeg lum.jpg --tone-core lum --lum-norm y

# Use a different RAW restoration or delivery gamut
python -m dngscan photo.dng --jpeg photo_p3.jpg --highlight-mode reconstruct --output-gamut p3

# Deliberately apply the full-frame brightness reference
python -m dngscan photo.dng --jpeg reference.jpg --ev auto
```

Run `python -m dngscan --help` for the complete argument list.

## Calibration assets and licence

The project keeps the runnable code, spectral bootstrap data, and open-licence
provenance assets in this repository. Optional proprietary vendor LUTs stay local and
are ignored by Git. The current scene-transform calibration data and its limits are
documented in [`dngscan_assets/spectral/README.md`](dngscan_assets/spectral/README.md).

dngscan is licensed under [GPL-3.0-or-later](LICENSE). Its AgX implementation derives
from darktable's GPL-3.0-or-later AgX code; third-party notices, including the historical
Tony McMapface LUT, are in [NOTICE.md](NOTICE.md).
