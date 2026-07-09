# dngscan Assets

Bundled third-party assets used or referenced by dngscan.

- `darktable_agx.c` / `darktable_agx.cl` — reference copies from darktable's AgX
  implementation, redistributed under GPL-3.0-or-later. The AgX curve construction and
  the C1 endpoint DRT are derived from these.
- `tony_mc_mapface.spi3d` — **historical.** The Tony McMapface LUT from an earlier
  experiment. The current pipeline (AgX / luminance / neutral tone cores) never samples
  it at runtime and no CLI flag references it; it is kept only for provenance and is
  redistributed under the upstream MIT option (`TONY_LICENSE-MIT.md`).

Spectral calibration inputs live under `spectral/` — see `spectral/README.md`.
