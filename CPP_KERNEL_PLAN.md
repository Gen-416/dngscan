# dngscan C++ Native Kernel Plan

> Status: design handoff for implementation. This document deliberately scopes the
> first native backend narrowly. Do not start by rewriting the complete RAW pipeline.
>
> Primary objective: accelerate the existing Python/NumPy AgX render hot path without
> changing the tone-plan semantics, output controls, or the Python renderer's role as
> the reference and fallback implementation.

## 1. Decision Summary

`dngscan` should gain an **optional, portable C++ CPU backend** for the existing
darktable-derived AgX formation and curve core. The first implementation targets only
the normal `tone_core == "agx"` path, including optional hue restoration and the
existing scene-driven Oklab `punch` operator.

The native backend must be an implementation detail of the current pipeline, not a new
rendering pipeline:

```text
RAW decode / demosaic / WB / camera matrix              Python + rawpy/LibRaw
RAW-derived clip masks, reconstruction, scene transform Python + NumPy
scene-linear Rec.2020 Nx3 float32
        |
        +--> AgX formation + C1 curve + hue mix + punch C++ V1 target
        |
display filter / look / output gamut fit                Python + NumPy
deterministic dither / JPEG ICC embedding / encoding    Python + Pillow/ImageIO
```

This is the correct split for both fidelity and engineering risk:

- The RAW-aware parts are dngscan's differentiator: CFA clipping evidence, highlight
  reconstruction, clip retreat, analysis-driven tone plans, and pre-AgX transforms.
  Replacing them prematurely risks losing the information that makes the tool useful.
- The expensive operation after those decisions is a pure, per-pixel float transform.
  It has a clean native-kernel boundary and is straightforward to validate against the
  current Python implementation.
- The current Python path stays permanent. Native unavailability, unsupported modes,
  or a numerical mismatch must silently fall back to it unless an explicit debug mode
  requests a hard failure.

Do **not** include Metal in this first change. A C++ kernel with a narrow immutable
parameter contract gives us a sound baseline for a later Metal backend; doing both at
once makes it impossible to distinguish algorithmic, packaging, and GPU-transfer
regressions.

## 2. Target and Non-Goals

### V1 goals

1. Lower the CPU time of the existing normal AgX core on full-resolution images.
2. Preserve the same `ToneCompressionPlan` and `RenderPlan` decisions made in Python.
3. Preserve final `uint8` output exactly for the approved regression corpus whenever
   the native backend is selected.
4. Keep all GUI and CLI flags unchanged. The backend is selected automatically.
5. Be optional: a source checkout without a compiler, an unsupported OS, or a failed
   native import still runs the complete Python version.
6. Release the GIL during the native loop, but do not introduce an additional native
   thread pool in V1.

### Explicit V1 non-goals

- No replacement for rawpy/LibRaw, demosaic, black/white-level handling, or `analyze`.
- No native high-light reconstruction, CFA clip-mask construction, raw guidance, or
  `clip_retreat`.
- No `lum`, `neutral`, or `gated` tone core. They keep using Python until each has its
  own reference parity suite.
- No output gamut fit, display filter, vendor LUT loader, Oklab display look, dithering,
  ICC handling, or JPEG encoder.
- No HDR gain-map work.
- No OpenMP, no hand-written AVX/NEON, no Metal, and no `-ffast-math` in the first pass.

This scope is intentional. The benchmarked full-frame AgX part was the costly,
embarrassingly parallel math after our existing Python-side memory and chunking work.
Adding unrelated pipeline stages weakens the ability to prove that a changed render
still means exactly the same thing.

## 3. Current Reference Path

Cursor should treat the following Python functions as the behavioral specification,
not the darktable C source alone:

| Stage | Current source of truth | V1 native? |
| --- | --- | --- |
| scene scaling, optional pre-AgX transform | `dngscan/render.py:scene_rec2020_to_float`, `dngscan/scene_transform.py` | No |
| RAW clip retreat | `dngscan/retreat.py` | No |
| AgX gamut guard | `dngscan/agx.py:compress_into_gamut` | Yes |
| inset / outset geometry | `dngscan/agx.py:formation_matrices`, `apply_core` | Yes |
| C1 endpoint curve parameter compilation | `dngscan/drt.py:curve_params_from_plan` | Python prepares parameters |
| C1 curve application | `dngscan/agx.py:apply_curve` / `dngscan/drt.py:apply_c1_endpoints` | Yes |
| optional hue restoration | `dngscan/agx.py:_rgb_to_hsv`, `_mix_hue`, `_hsv_to_rgb` | Yes |
| optional scene-driven punch | `dngscan/punch.py:apply_punch_rec2020` | Yes |
| output-space gamut fit and post-look | `dngscan/render.py`, `dngscan/color.py`, `dngscan/look.py` | No |
| quantization and JPEG | `dngscan/render.py:dither_quantize_u8`, `dngscan/export.py` | No |

The existing convergence point is `dngscan/render.py:apply_agx_core()`. It calls:

```python
inset, outset = agx_engine.formation_matrices(plan)
mapped = agx_engine.apply_core(rgb_rec2020, plan, inset, outset)
return punch_engine.apply_punch_rec2020(mapped, plan.punch_strength)
```

The native dispatch should replace only this sequence. It must not create a parallel
set of tone-plan logic or infer exposure/white points itself.

## 4. Proposed Source Layout

There is currently no packaging or CMake scaffold in the repository. Add it without
moving the Python package or turning the project into a C++ application.

```text
pyproject.toml                         # Python package + optional native build config
CMakeLists.txt                         # small top-level delegator
cpp/
  CMakeLists.txt
  include/dngscan_fast/
    agx_core.h                         # POD parameter types and pure kernel API
  src/
    agx_core.cpp                       # scalar reference-native implementation
    bindings.cpp                       # pybind11 boundary only
dngscan/
  _fast.py                             # import/dispatch/fallback policy
  fast_plan.py                         # Python plan compilation + cache
tests/
  test_fast_backend.py                 # unit, parity, dispatch tests
tools/
  benchmark_fast_backend.py            # repeatable native vs Python benchmark
```

Use **C++17**, **CMake**, **pybind11**, and **scikit-build-core**. Do not add Eigen,
OpenCV, OpenMP, a shader compiler, or an external SIMD abstraction in V1. The kernel is
small enough that scalar C++ is the correct first correctness target; modern compilers
may auto-vectorize later after parity is established.

### Packaging policy

Native acceleration must not make the project harder to install for users who only need
the Python renderer.

Recommended rollout:

1. Keep the ordinary Python package installable without compiling C++.
2. Provide a developer/native extra, for example `pip install -e '.[native]'`, which
   installs build requirements and enables CMake to build `_dngscan_fast`.
3. In CI/release work, produce wheels with the extension for macOS universal2, Linux
   x86_64/aarch64, and Windows only after those wheels pass parity tests. Use
   `cibuildwheel` for this phase.
4. `dngscan/_fast.py` catches `ImportError` and exposes `available() == False`; the rest
   of the application must never import pybind11 directly.

Do not make `pip install .` fail because a friend has no compiler. A separate optional
native distribution is acceptable during early development if making an in-package
optional extension portable proves awkward. The Python API must not care which delivery
mechanism was used.

## 5. Public Python Boundary

Create `dngscan/_fast.py` as the only native-facing Python module. It owns importing,
input validation, plan compilation, feature checks, and fallback reporting.

Suggested public surface:

```python
# dngscan/_fast.py
from __future__ import annotations

def available() -> bool: ...
def backend_name() -> str: ...              # "cpp" or "numpy"
def supports_agx(plan: ToneCompressionPlan) -> bool: ...
def compile_agx_plan(plan: ToneCompressionPlan) -> NativeAgxPlan: ...

def apply_agx_core_f32(
    rgb: np.ndarray,                         # (N, 3), C-contiguous float32
    plan: NativeAgxPlan,
) -> np.ndarray:                            # new (N, 3) C-contiguous float32
    ...
```

`NativeAgxPlan` is a small immutable pybind11 class backed by a C++ POD struct. Python
constructs it from a current `ToneCompressionPlan`; C++ never receives a dataclass,
dictionary, GUI option, or a mutable Python object.

The dispatch rule inside `render.apply_agx_core` should be structurally similar to:

```python
def apply_agx_core(rgb_rec2020, plan):
    if fast_backend.can_use_agx(rgb_rec2020, plan):
        try:
            return fast_backend.apply_agx_core_f32(rgb_rec2020, plan)
        except fast_backend.NativeKernelError:
            if fast_backend.strict_requested():
                raise
            # Fall through to reference path; emit at most debug logging.

    inset, outset = agx_engine.formation_matrices(plan)
    mapped = agx_engine.apply_core(rgb_rec2020, plan, inset, outset)
    return punch_engine.apply_punch_rec2020(mapped, float(plan.punch_strength))
```

`can_use_agx` must return `False` for:

- `tone_core != "agx"`;
- unavailable extension;
- non-`float32` arrays where conversion would be surprising;
- malformed dimensions or nonfinite plan parameters;
- a future feature that is not represented in `NativeAgxPlan` yet.

The wrapper may call `np.ascontiguousarray(rgb, dtype=np.float32)` when it is safe to do
so. It must never mutate the caller's buffer. Preserve the current output contract: a
new `float32 (N, 3)` array.

### Backend control for tests and diagnosis

Support an environment variable with three values:

```text
DNGSCAN_FAST=auto    # default: use C++ when supported, otherwise NumPy
DNGSCAN_FAST=0       # force NumPy reference path
DNGSCAN_FAST=1       # require C++ for supported AgX calls; raise on a native failure
```

This is intentionally not a normal GUI control. It is an implementation/debug switch,
useful for parity tests and field reports, not a creative rendering option.

## 6. Immutable Native Parameter Contract

Do **not** reimplement `ToneCompressionPlan` construction in C++. Python already
combines scene analysis, RAW evidence, darktable-style defaults, user selection, and
look-specific plan overrides. The native kernel receives the final, already-resolved
numbers.

At a minimum the C++ `NativeAgxPlan` needs the following fields. Store matrices in row
major order, exactly matching `dngscan.color.apply_rgb_matrix3`.

```cpp
struct CurveParams {
  float black_ev;
  float range_ev;
  float gamma;
  float target_black;
  float target_white;

  float toe_power;
  float toe_transition_x;
  float toe_transition_y;
  float toe_scale;
  bool  need_convex_toe;
  float toe_fallback_power;
  float toe_fallback_coefficient;

  float slope;
  float intercept;

  float shoulder_power;
  float shoulder_transition_x;
  float shoulder_transition_y;
  float shoulder_scale;
  bool  need_concave_shoulder;
  float shoulder_fallback_power;
  float shoulder_fallback_coefficient;
};

struct NativeAgxPlan {
  float inset[9];
  float outset[9];
  CurveParams curve;
  float hue_keep;
  float view_brightness;
  float punch_strength;

  // Fixed Rec.2020/XYZ/Oklab matrices copied from Python constants at plan build time.
  float rec2020_to_xyz[9];
  float xyz_to_rec2020[9];
  float oklab_m1[9];
  float oklab_m2[9];
  float oklab_m1_inv[9];
  float oklab_m2_inv[9];
};
```

Python must create `CurveParams` by calling the existing
`dngscan.drt.curve_params_from_plan(plan)`, not by duplicating `_build_curve_params`.
The plan compiler should similarly obtain `inset/outset` through
`dngscan.agx.formation_matrices(plan)`. This guarantees that a future preset or
darktable-aligned parameter change still feeds the same data to both implementations.

Cache compiled native plans in Python using an immutable key made from all effective
plan values and matrix contents. A reasonable V1 key is a tuple of the fields listed
above. Do not cache by object identity because plans are commonly created with
`dataclasses.replace`.

### Numerical constants

Keep the following values synchronized with Python rather than inventing native
equivalents:

```text
EPS                         = dngscan.agx.EPS
Rec.2020 luminance          = (0.2627, 0.6780, 0.0593)
AgX inset / outset          = Python formation_matrices(plan)
RGB/XYZ/Oklab matrices      = dngscan.constants
punch thresholds and gains  = dngscan.punch constants
skin hue interval           = dngscan.punch constants
```

The safest V1 design passes matrices as data and keeps only the scalar thresholds in
the extension. Add a `native_abi_version` integer to the binding. If the Python
compiler and binary disagree, `available()` must return false rather than rendering
with a stale parameter layout.

## 7. Exact Native Algorithm

Implement scalar helpers first. The code should mirror the operation order of
`dngscan.agx.apply_core` and `dngscan.punch.apply_punch_rec2020`, not a mathematically
"equivalent" rearrangement. Small rearrangements affect highlight hue, threshold edges,
and final 8-bit rounding.

For every pixel `rgb`:

```text
1. AgX gamut guard in Rec.2020
   rgb = compress_into_gamut(rgb)

2. Formation geometry
   inset_rgb = inset_matrix * rgb

3. Optional pre-curve hue record
   if hue_keep < 0.999:
       pre_hue = hue(rgb_to_hsv(max(inset_rgb, 0)))

4. Per-channel C1 endpoint curve
   ev = log2(max(inset_rgb / 0.18, EPS))
   x = clamp((ev - black_ev) / range_ev, 0, 1)
   encoded = apply_curve_c1(x, curve)
   linear = pow(max(encoded, 0), gamma)
   if view_brightness != 1:
       linear = pow(max(linear, 0), 1 / view_brightness)

5. Optional hue restoration
   if hue_keep < 0.999:
       linear = mix_hue_shortest_arc(linear, pre_hue, hue_keep)

6. Outset geometry
   mapped = outset_matrix * linear

7. Optional scene-driven punch
   if punch_strength > 1e-3:
       mapped = apply_punch_rec2020(mapped, punch_strength)

8. return mapped as float32
```

### 7.1 `compress_into_gamut`

Port `dngscan.agx.compress_into_gamut` exactly. It is not the final display gamut fit.
It is a pre-inset safety operation that removes negative components while preserving the
Rec.2020 luminance behavior used by the current AgX implementation.

Do not replace it with `max(rgb, 0)` and do not use display gamut matrices here. The
current steps are:

```text
input_y = dot(REC2020_Y, rgb)
max_rgb = max(r, g, b)
opponent = max_rgb - rgb
y_compensate_negative = max(opponent) - dot(REC2020_Y, opponent) + input_y

offset = max(-min(rgb), 0)
rgb_offset = rgb + offset
opponent_offset = max(rgb_offset) - rgb_offset
y_new = max(opponent_offset) - dot(REC2020_Y, opponent_offset) + dot(REC2020_Y, rgb_offset)

ratio = y_compensate_negative / y_new only when y_new > y_compensate_negative and y_new > EPS
return rgb_offset * ratio
```

### 7.2 Matrix operations

Use explicit three-component operations, not a generic dynamic matrix library:

```cpp
inline Rgb mat3(const float m[9], Rgb v) {
  return {
    m[0] * v.r + m[1] * v.g + m[2] * v.b,
    m[3] * v.r + m[4] * v.g + m[5] * v.b,
    m[6] * v.r + m[7] * v.g + m[8] * v.b,
  };
}
```

This makes row/column interpretation explicit and avoids allocations. Validate matrix
orientation with a direct Python/C++ test using three basis colors before attempting
image parity.

### 7.3 C1 curve

Port `agx.apply_curve()` directly:

- `x < toe_transition_x`: either the fallback power curve or the scaled sigmoid;
- `x > shoulder_transition_x`: either the fallback power curve or the scaled sigmoid;
- otherwise: `slope * x + intercept`;
- clamp output to `[target_black, target_white]`.

Use the current Python conditions exactly; equality belongs to the middle segment. The
curve is C1 by construction, but its branch choice and the fallback branches are part
of its definition. Do not recompute `scale`, transition points, adaptive gamma, pivot,
or latitude in C++ V1.

The scalar functions map one-to-one to the existing Python names:

```text
agx.sigmoid        -> sigmoid
agx.scaled_sigmoid -> scaled_sigmoid
agx.apply_curve    -> apply_curve_c1
drt.apply_c1_endpoints -> log2 + normalize + apply_curve_c1 + gamma
```

### 7.4 HSV hue path

The HSV routines need fidelity attention because hue selection around equal channels is
observable. Port these semantics from `_rgb_to_hsv` / `_hsv_to_rgb`:

- `delta <= EPS` produces hue `0`.
- Red wins ties (`maxc == r`); green only wins when it is max and red did not win;
  blue takes the remaining max cases.
- HSV saturation is zero when `maxc <= EPS`.
- Hue restore takes the shortest wrapped arc:

  ```text
  delta = post_hue - pre_hue
  delta -= rint(delta)       # ties-to-even, same as NumPy rint
  restored_hue = (pre_hue + hue_keep * delta) mod 1
  ```

`std::nearbyintf` with the default IEEE round-to-nearest-even mode is the closest
portable spelling of NumPy `rint`. Add an explicit unit test for `+/-0.5` hue deltas.
Do not use `std::round`, which rounds halves away from zero and changes hue at the wrap
boundary.

### 7.5 Punch operator

Punch is part of the normal AgX render contract, even though its strength is usually
zero. When nonzero, port `punch.apply_punch_rec2020` in the same order:

```text
Rec.2020 -> XYZ -> LMS -> cbrt -> Oklab
compute chroma and hue
compose neutral/shadow/highlight/chroma/skin weights
gain = 1 + (PUNCH_CHROMA_MAX - 1) * strength * weight
scale Oklab a,b by gain
Oklab -> LMS^3 -> XYZ -> Rec.2020
nan_to_num equivalent
```

The native version must preserve punch's identity short-circuit for
`strength <= 1e-3`. This avoids touching current night-scene renders where punch is
intentionally disabled and lets the Python/numerical identity test stay exact.

The `smoothstep` and skin-hue arc functions should be ported from `dngscan.look`, not
approximated with a different saturation curve. Treat hue `20..60 degrees` and the
current damp/gain constants as plan-independent source constants in V1.

## 8. Floating-Point and Determinism Contract

The user-facing quality bar is not merely "looks close." The backend must protect a
scientific image pipeline whose existing output is regression-tested at the final 8-bit
array level.

### Build flags

Start with conservative optimization:

```text
C++ standard:          C++17
Optimization:          -O3 (or /O2 on MSVC)
Fast math:             prohibited
Floating contraction:  disabled (-ffp-contract=off where supported)
```

Do not use `-Ofast`, `-ffast-math`, unsafe reciprocal math, relaxed NaN behavior, or
explicit FMA in the strict implementation. They may be useful later behind a separate
non-strict benchmark option, never as the default backend.

Use `float` arithmetic within the pixel kernel and obtain parameter values as `float32`.
Python currently creates float32 image buffers, but NumPy scalar expressions and libm
can still have platform-specific rounding. Therefore exactness must be tested, not
assumed from the type alone.

### NaN and infinity behavior

Existing punch performs:

```python
np.nan_to_num(rgb, nan=0.0, posinf=1e6, neginf=0.0)
...
np.nan_to_num(out, nan=0.0, posinf=1e6, neginf=-1e6)
```

The native punch path must reproduce those limits. Inputs should normally be finite;
nevertheless this behavior prevents a malformed pixel from making an entire JPEG
unusable. Add direct NaN, `+inf`, and `-inf` unit cases.

### What must remain in Python in V1

Keep `dither_quantize_u8` in Python. It uses NumPy's PCG random sequence; reproducing
that sequence in C++ is unrelated to AgX speed and would turn a small float difference
into a full-frame byte mismatch. Native output feeds the existing Python finalization,
then the existing deterministic quantizer.

## 9. Integration Details

### 9.1 Render paths

`render_output_u8()` is the optimized production render path. It already processes
chunks and may run two Python worker chunks. Its invocation reaches
`apply_tone_core()` and then `apply_agx_core()`.

Integrate at `apply_agx_core()` only. That automatically covers:

- full-resolution export;
- proxy preview;
- auto/manual exposure probes that use the same renderer;
- sRGB and Display P3 final output;
- `base`, `punchy`, `muted`, and `smooth` primaries plans;
- core-level look overrides such as hue-keep or target white that have already been
  compiled into the plan.

Do not write a second native call branch in both `render_output_linear()` and
`render_output_u8()`. One dispatch point prevents divergence.

### 9.2 Modes that intentionally keep Python

For V1:

```text
agx      -> native when available and supported
neutral  -> Python
lum      -> Python
gated    -> Python
```

`gated` combines raw guidance, clip masks, and two tone paths. It is a poor first
native target because its value comes from RAW-aware decision logic, not raw arithmetic
throughput. Do not accidentally route it to native `agx` merely because it contains an
AgX subpath; that would silently alter the intended blend.

### 9.3 Threading

The C++ loop should release the GIL using `py::gil_scoped_release`, then process the
provided contiguous block serially. Existing Python-level chunk parallelism is already
bounded. Adding OpenMP or a second C++ pool would oversubscribe cores and can make GUI
preview latency worse while an export is active.

Only revisit native parallelism after benchmark data shows that the current two-chunk
render scheduler is a bottleneck. If it is added, it needs a single global policy so
Python workers and C++ workers never multiply each other.

### 9.4 Error behavior

- Invalid array shape/dtype: Python wrapper falls back before C++ is called.
- Extension import failure: normal Python behavior, no modal GUI warning.
- C++ exception: wrap as `NativeKernelError`; `auto` falls back, `DNGSCAN_FAST=1` raises.
- ABI version mismatch: backend unavailable.

Do not broadly catch `Exception` around the entire render. Bugs in plan creation or
unrelated Python code must still fail normally.

## 10. Build Plan

### Phase 0: establish a benchmark and immutable test corpus

Before writing C++, add a small benchmark script that can force `DNGSCAN_FAST=0` and
reports at least:

```text
AgX-core time only
full render_output_u8 time
export wall time excluding/including JPEG write
peak RSS when available
```

Use median of at least three warm runs. Current reference observations on a full
24 MP `_SDI0150.DNG` are approximately:

```text
legacy render core:        10.218 s
current fused Python path:  5.475 s
full GUI export:           ~13 s, depending on JPEG quality and disk write
```

These are context, not a promise. Record machine, Python version, compiler, image
dimensions, tone mode, output gamut, and quality beside every new number.

### Phase 1: standalone C++ correctness proof

Implement `agx_core.cpp` as a normal C++ library with a small CLI or a pybind test
binding. First validate synthetic arrays before connecting it to the production renderer:

1. neutral gray ramp, including `0`, `EPS`, 18%, and values above the shoulder;
2. pure R/G/B/cyan/magenta/yellow ramps through high light;
3. negative Rec.2020 components exercising `compress_into_gamut`;
4. hue wrap cases around 0/1 and half-turn rounding;
5. all C1 branch combinations, including fallback toe and fallback shoulder;
6. punch zero, small nonzero, and maximum strength;
7. NaN and infinity handling.

At this stage output can be compared in float with an explicit tolerance to locate
formula errors. Do not claim byte parity yet.

### Phase 2: pybind11 extension and Python dispatch

Add `_dngscan_fast`, `_fast.py`, and `fast_plan.py`. The binding should:

- accept only an `N x 3` contiguous `float32` NumPy array;
- allocate a distinct `N x 3` `float32` result;
- release the GIL only around the native loop;
- never hold a Python object reference in the loop;
- expose ABI version and a basic `self_test()` if useful for diagnostics.

Route only `apply_agx_core()` through the wrapper. Run the full existing test suite with
the backend forced off and then forced on.

### Phase 3: production parity gate

Add native/reference parity tests and require them in CI where native compilation is
enabled. The final production criterion is:

```python
np.testing.assert_array_equal(native_u8, reference_u8)
```

Run this over the local DNG regression corpus for both output gamuts and all supported
highlight modes. If a platform cannot meet final-U8 equality due to libm behavior,
temporarily mark its native backend unavailable rather than shipping an unverified
variant.

### Phase 4: packaging and releases

Only after Phase 3 is stable:

- add `cibuildwheel` workflows;
- build macOS universal2 first (the primary desktop target);
- add Linux wheels next;
- add Windows only after build flags and parity are proven;
- retain source-only Python fallback indefinitely.

## 11. Test Matrix

Use `unittest`, matching the repository's existing test style. Add a native test module
that skips native-specific assertions only when the extension was not built; it must
never cause the normal pure-Python suite to fail merely because C++ is absent.

### Required unit tests

```text
test_fast_unavailable_falls_back
test_fast_rejects_non_agx_cores
test_fast_accepts_c_contiguous_float32
test_fast_does_not_mutate_input
test_fast_matrix_orientation_matches_python
test_fast_gamut_guard_matches_python
test_fast_curve_each_branch_matches_python
test_fast_hsv_tie_break_and_shortest_arc_matches_python
test_fast_punch_zero_is_identity
test_fast_punch_matches_python
test_fast_nan_inf_contract_matches_python
test_fast_abi_mismatch_is_unavailable
```

### Required render parity tests

For a fixed small synthetic scene and, locally, for the supplied DNG corpus:

```text
output gamut:        sRGB, Display P3
highlight mode:      clip, blend, reconstruct
WB:                  camera, daylight
primaries presets:   smooth/default, base, punchy, muted
hue_keep:            0, intermediate, 1
punch:               0 and nonzero
look:                none and an installed non-vendor project look
scene transform:     none and supported scene-transform option
```

The final check is byte equality of U8 results. It tests the effect that matters to the
saved JPEG while retaining existing deterministic dither in Python.

Test special routing explicitly:

```python
for core in ("neutral", "lum", "gated"):
    # Assert Python path used and output remains unchanged from forced NumPy.
```

Use the existing `tests/test_stream_render.py` as the model for strict U8 comparisons.
Do not make public CI depend on private image files. Put those paths behind a local
benchmark/regression command, and keep deterministic synthetic cases in the repository.

## 12. Acceptance Criteria

The implementation is ready to merge only when all of the following are true:

1. `DNGSCAN_FAST=0` runs every existing test unchanged.
2. On a machine with the extension, `DNGSCAN_FAST=1` passes all supported AgX unit and
   U8 parity tests.
3. `neutral`, `lum`, and `gated` renders remain on the Python implementation and have
   no output regression.
4. The native module does not retain the input image after return and does not mutate
   it.
5. Normal package installation and source execution work when the native module is
   absent.
6. A full-resolution AgX benchmark provides a material, measured gain over the current
   fused Python path. Do not set an arbitrary target before measurement, but a result
   smaller than roughly 15% should trigger profiling before adding maintenance burden.
7. No extra native worker pool competes with the GUI export process.
8. The GUI/CLI present no new color or tone control and need no user education to use
   the optimized backend.

Suggested commands after implementation:

```bash
cd /Users/itoshikigen/projects/dngscan
.venv/bin/python -m unittest discover -s tests -q
DNGSCAN_FAST=0 .venv/bin/python -m unittest discover -s tests -q
DNGSCAN_FAST=1 .venv/bin/python -m unittest tests.test_fast_backend -q
.venv/bin/python tools/benchmark_fast_backend.py /Users/itoshikigen/Pictures/_SDI0150.DNG
```

## 13. License and Attribution

The project is GPL-3.0-or-later and already carries darktable AgX reference material in
`dngscan_assets/`, with notices in `NOTICE.md`. The Python curve implementation is
derived from the darktable GPL implementation and its OpenCL kernel.

The C++ port must:

- retain `SPDX-License-Identifier: GPL-3.0-or-later` in every new source file;
- state in `agx_core.cpp` that the curve/formation behavior is a port of the project's
  darktable-derived Python reference, with the existing darktable attribution link;
- update `NOTICE.md` if code is copied or closely ported from a new darktable source;
- avoid compiling `dngscan_assets/darktable_agx.c` directly. It relies on darktable's
  internal module framework and is a reference, not an embeddable library.

## 14. Later Work, After V1 Is Proven

The C++ kernel contract is designed to be reusable, but these are separate changes:

### SIMD CPU phase

After scalar C++ has strict parity, profile before writing intrinsics. If `pow`, `log2`,
`cbrt`, and `atan2` dominate, naive SIMD often cannot improve much without approximate
math, which would undermine byte parity. Start with compiler vectorization reports. A
fast-but-not-bit-identical backend should only exist as an opt-in experiment, never
replace the strict default silently.

### Broaden native coverage

Possible future candidates, each with its own parity plan:

1. `scene_transform` and `clip_retreat` as a separate pre-core kernel;
2. display-side Oklab gamut fitting;
3. `lum` core;
4. `gated` core only after raw guidance/mask alignment contracts are fully specified.

Do not fuse all of them merely to avoid temporary buffers until profiling shows the
memory traffic dominates. The current Python pipeline's chunk boundaries and tests are
valuable correctness boundaries.

### Metal backend

Metal is worthwhile on macOS only after the CPU ABI is stable. The same
`NativeAgxPlan` should be serializable into a Metal constant buffer, and the same
`Nx3 float32` input/output contract should work for a compute kernel. However:

- small proxy previews can be faster on CPU due to upload/download overhead;
- JPEG/export still needs CPU-side finalization unless more stages move together;
- GPU numerical functions may differ more than C++ libm, so its acceptance standard
  should initially be perceptual/error-bound validation, not a claim of U8 identity;
- Metal must remain a macOS optional backend, never the only renderer.

This makes C++ V1 the useful foundation: it establishes the exact sequence, immutable
plan data, tests, and performance baseline that a Metal experiment would otherwise lack.

## 15. Cursor Execution Checklist

Cursor should implement in this order and stop to run tests after each numbered item:

1. Read `dngscan/agx.py`, `dngscan/drt.py`, `dngscan/punch.py`, and
   `dngscan/render.py:apply_agx_core` in full. Treat Python as specification.
2. Add the CMake/pybind scaffold and a native availability loader. Verify the project
   still works when no extension is built.
3. Implement the scalar AgX core without punch. Add synthetic float parity tests.
4. Add HSV hue restoration and branch-edge tests.
5. Add punch and NaN/inf behavior.
6. Add plan compilation from existing Python helpers, with a cache keyed by resolved
   numerical values.
7. Add dispatch at the single `apply_agx_core` convergence point.
8. Add final-U8 parity tests against forced Python on synthetic data and local DNGs.
9. Measure before/after, inspect CPU utilization and RSS, then decide whether compiler
   vectorization or a later SIMD phase is justified.
10. Only then add wheel CI and document the optional native installation path.

At every stage: do not alter the visible tone options, defaults, analysis logic, or
current color behavior merely to accommodate the native code. The C++ backend must be a
compiled implementation of the current AgX decision, not a second interpretation of it.
