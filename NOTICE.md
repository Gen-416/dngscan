# Third-party notices

## darktable AgX (GPL-3.0-or-later)

The `agx` tone-mapping mode in `dngscan.py` ports portions of the AgX view-transform
implementation from darktable:

- https://github.com/darktable-org/darktable/blob/master/src/iop/agx.c
- https://github.com/darktable-org/darktable/blob/master/data/kernels/agx.cl

darktable is licensed under GPL-3.0-or-later. Because this project incorporates that
code, the combined work is distributed under **GPL-3.0-or-later** as well.

The AgX inset/outset primaries derive from Troy Sobotka's AgX family of view
transforms.

## Tony McMapface LUT (Apache-2.0 OR MIT)

The `tony` mode samples `tony_mc_mapface.spi3d`, an external asset from:

- https://github.com/h3r2tic/tony-mc-mapface

It is dual-licensed under Apache-2.0 OR MIT. The LUT file is **not** redistributed
with this repository; download it from the upstream project and place it at
`~/dngscan_assets/tony_mc_mapface.spi3d` (or pass `--tony-lut`).

## libultrahdr (Apache-2.0)

Ultra HDR export can optionally call Google's `ultrahdr_app` from:

- https://github.com/google/libultrahdr

libultrahdr is licensed under Apache-2.0. It is **not** redistributed with this
repository; install it separately (for example `brew install libultrahdr`) if the
macOS ImageIO gain-map backend is not sufficient.
