# dngscan — roadmap / continue-here notes

Stage checkpoint for picking work back up. Everything below is on `main`.

**Run it:** no system Python has the deps; use the project venv.
```bash
cd ~/projects/dngscan
source .venv/bin/activate
python -m dngscan.gui                     # GUI
python -m dngscan photo.dng --jpeg out.jpg --jpeg-mode agx   # CLI
```

## Done recently
- **Demosaic on export**: `--demosaic` (default `auto` → DHT; non-Bayer → libraw
  native). Export only; preview stays on the fast half-size path. No noise reduction
  anywhere in the pipeline.
- **Oklab hue-preserving gamut fit** at the output stage (`fit_to_output_gamut`,
  adaptive-L0, α=0.05), every mode, sRGB + P3. Replaced per-channel clipping.
- **AgX = pure Troy sigmoid**: removed the dead linear-latitude branch; gamut
  compression now uses Rec.2020 luminance weights (pre-inset).
- **Analysis matches the export**: `render_to_xyz` uses the same demosaic + highlight
  mode as the export buffer (kept `user_flip=0`). CFA/raw-domain analysis stays
  independent of demosaic/highlight.
- **Chroma subsampling**: `--chroma {444,422,420}` (default 444) + GUI dropdown. SDR
  path only. 4:2:0 ≈ halves size at same quality.

## Next up — HDR gain-map refactor (priority)
Principle: **the base image and the gain map must share ONE SDR-linear** so that
`base × gain = HDR` reconstructs correctly. Currently they diverge; do this as one
refactor:

1. Compute a single `sdr_base_linear` = output-linear → `fit_to_output_gamut(…, "p3")`
   → clamp [0,1].
2. Base image = OETF(`sdr_base_linear`) + TPDF dither.
   - **Bug to fix here:** `export_ultrahdr_jpeg` (dngscan/core.py ~L1498) calls
     `output_linear_to_u8(sdr_linear)` **without** `output_gamut="p3"`, so the P3 base
     is gamut-fit to sRGB — throws away the wide-gamut color HDR is meant to show.
3. Gain map = `log2(hdr_linear / max(sdr_base_linear, eps))`, clip [0, headroom], with
   **TPDF dither before the 8-bit round** (`compute_gainmap_u8` currently uses plain
   `np.round` → banding in HDR highlight rolloff). Denominator MUST be the same
   `sdr_base_linear` (it currently uses the pre-fit `sdr_linear` → base/gain mismatch).

Implementation hint: split `output_linear_to_u8` into "fit → linear" and "linear → u8"
so the base and the gain-map denominator can share the fitted linear.

Optional: 3-channel gain map (keeps saturated-highlight *color* in HDR; larger file).
Currently single-channel (luminance ratio).

**Validation gate:** open the output in an Android / Chrome Ultra HDR reader to confirm
cross-platform reconstruction (Apple JPEG-MPF vs Android ISO 21496-1 interop).

## Optional / later
- **Downscale for delivery**: `--max-long-edge N`. Resize the *output-linear* buffer
  with Lanczos (in linear light) before encode — do NOT resize the gamma-encoded 8-bit.
  Not urgent (social platforms downscale anyway). Lanczos is the right algorithm; it's
  already used in `resize_gainmap_u8`.
- HDR base could also honor `--chroma` (left at 4:4:4 for now).

## Notes
- `.venv/` is gitignored; deps in `requirements.txt` (no system Python has them).
- Dev test file: `~/Pictures/_SDI0165.DNG` (not in repo).
- Defaults are intentionally max-fidelity (quality 100, 4:4:4); use `--jpeg-quality`
  and `--chroma` to shrink for delivery.
