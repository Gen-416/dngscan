# dngscan Assets

Open-source references and calibration inputs used by dngscan.

- `darktable_agx.c` / `darktable_agx.cl` — reference copies from darktable's AgX
  implementation, redistributed under GPL-3.0-or-later. The AgX curve construction and
  the C1 endpoint DRT are derived from these.
Spectral calibration inputs live under `spectral/` — see `spectral/README.md`.

No vendor LUT is distributed. Local LUT downloads and generated look fields are ignored
by Git and must not be committed without an explicit redistribution licence.
