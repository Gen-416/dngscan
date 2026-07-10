# dngscan — guardrails & parked work: implementation handoff

> Status: design handoff for implementation. Ordered by priority; items 1–3 are the
> point of this document, items 4–6 are parked capabilities with their designs written
> down so they can be picked up without re-deriving context.
>
> Motivating history (why guardrails outrank features now): this codebase shipped three
> defects through a fully green test suite — shoulder-latitude that was inert on real
> images, punchy/muted primaries presets whose purity ordering was inverted (the test
> asserted with `linear @ M`, which exercises the transpose, not the pipeline's
> left-multiply), and a plain CLI export that crashed with exit 1 *after* writing the
> JPEG (`csv_row` read gamut keys the subset analysis no longer computes). All three
> share one root cause: nothing guards whole-image rendered behavior, and nothing runs
> the suite in an environment other than the author's machine.

---

## 1. CI (GitHub Actions) — do this first

**Goal.** Every push runs the full suite on a machine that is not the author's, builds
the native kernel, and proves native/NumPy parity in strict mode.

**Architecture.** One workflow, `.github/workflows/ci.yml`:

- Matrix: `ubuntu-latest` + `macos-14`, Python 3.11 and 3.12 (keep the matrix small).
- Steps per job:
  1. checkout, setup-python;
  2. `pip install -r requirements.txt` (set `MPLBACKEND=Agg` for headless matplotlib);
  3. `python -m unittest discover tests` — **NumPy reference path** (`DNGSCAN_FAST=0`);
  4. `pip install pybind11 cmake` and run `tools/build_native.sh`
     (the script already falls back from `sysctl` to `nproc`; verify it on Linux and
     patch the `.so` glob if the suffix differs);
  5. `DNGSCAN_FAST=1 python -m unittest discover tests` — **strict native mode**: any
     silent fallback becomes a hard error, and `tests/test_fast_backend.py` parity
     assertions then certify the kernel against the NumPy reference on that platform.
- Tests requiring real RAW files or vendor LUTs already skip cleanly (4 skips today);
  CI must tolerate skips but fail on errors/failures.

**Acceptance.** Green matrix on a PR that touches `dngscan/`; a deliberately broken
kernel constant makes the strict job fail while the NumPy job stays green.

**Phase 2 (separate PR).** `cibuildwheel` on version tags. `pyproject.toml` already
uses scikit-build-core; wire `cpp/CMakeLists.txt` into the wheel build so
`pip install dngscan` ships `_dngscan_fast` without the user owning cmake. The pure
NumPy path must remain fully functional in an sdist install — native stays optional.

---

## 2. Golden-sample regression set

**Goal.** A committed set of small scenes whose rendered output is pinned, so that any
change to whole-image behavior — intended or not — is visible in review instead of
being discovered on real photographs weeks later.

**Architecture.**

- Location: `tests/golden/` (fixtures) + `tests/test_golden_render.py` (runner) +
  `tools/regen_golden.py` (intentional-change workflow).
- **Scenes** (all deterministic, seeded, small — target ≤ 128×128, total suite < 10 s):
  synthetic archetypes matching the failure classes already hit in this project:
  1. daylight wide-DR with saturated mid-tone patches (purity/wash regressions);
  2. night sparse-emitter: dark body + a few near-clip "lamps" (dark-frame/glare,
     `view_brightness`, sparse-emitter shoulder);
  3. high-key scene (auto-EV must not gray-world it);
  4. skin-tone patch grid spanning the skin hue arc (punch skin damping, looks);
  5. neutral ramp + hue wheel at three luminance levels (hue skew, banding, gray-axis
     purity);
  6. staggered-clip highlight gradient with synthetic CFA clip masks (retreat, gated
     core, per-channel clipping fringes).
  Optionally 1–2 tiny real-scene excerpts: heavily downsampled (~96×64) scene-linear
  Rec.2020 crops exported from the author's own DNGs via a small helper in
  `tools/regen_golden.py` and stored as `.npz` — no RAW redistribution concern.
- **Coverage matrix per scene**: cores `agx / gated / lum / neutral`; for `agx`
  additionally primaries `smooth / base / punchy / muted`. Rendered via
  `render_output_u8` with a synthetic `RawBundle` (follow the pattern in
  `tests/test_stream_render.py::_bundle_and_plan`, extended with `clip_masks` for the
  gated scenes).
- **Two test classes, deliberately distinct:**
  - `GoldenFixedPlan` — hand-written `ToneCompressionPlan`s (isolates the renderer:
    curve, formation, punch, retreat, finalize);
  - `GoldenCompiledPlan` — plans built by `build_render_plan` from the synthetic
    bundle (catches plan-compilation drift: endpoints, gates, latitude).
- **Assertions, two tiers:**
  - Tier 1 (strict): byte-equality of the u8 output against the stored `.npz`. This is
    the default; it makes "no behavior change" refactors provable.
  - Tier 2 (perceptual, printed on failure and checked with loose tolerances):
    per-scene Oklab statistics — mean/p90 chroma, luminance p10/p50/p99, per-ROI means
    for labelled regions (skin patch, lamp, gray axis). Purpose: when Tier 1 fails on
    an *intentional* change, the diff report quantifies what moved.
- **Intentional-change workflow:** `tools/regen_golden.py` re-renders everything,
  writes the new fixtures, and prints a per-scene delta table (max ΔE, which
  core/preset moved). That table goes into the commit message. Regeneration must be a
  conscious act, never automatic.
- Note: fixtures pin the **NumPy** path. The native kernel is covered transitively by
  the strict-mode CI job plus `test_fast_backend` parity — do not maintain two fixture
  sets.

**Acceptance.** Reverting the punchy/muted geometry fix (`_PUNCHY_GEOMETRY` ratio back
to 0.5) makes the golden suite fail with a delta table pointing at the saturated-patch
scenes. A whitespace refactor of `render.py` keeps it byte-green.

---

## 3. `DNGSCAN_DEBUG` traceback (trivial; bundle with item 1's PR)

**Goal.** The CLI's catch-all (`dngscan/cli.py`, `except Exception as exc: print
(f"error: {exc}")`) swallowed a real crash for days; the `'sRGB'` KeyError took four
debugging rounds because the stack was gone.

**Change.** In that handler: if `os.environ.get("DNGSCAN_DEBUG")`, call
`traceback.print_exc()` (stderr) before the one-line error; keep exit code 1. Apply
the same pattern to any GUI server catch-all that reduces an exception to a string.

**Acceptance.** `DNGSCAN_DEBUG=1 python -m dngscan bad-input …` prints a full
traceback; without the variable, output is unchanged.

---

## 4. (Parked) Corpus report tool — data for punch/gated thresholds

**Why parked.** The punch gate (`tone.py`: `w_bright` smoothstep(−3.0, −1.2),
`w_quality` (7.5, 9.5), `w_dr` (6.5, 8.0)) and the gated color-path window
(`color_path_highlight_ev` 0.25–2.75, `midtone_protect` 0.92) were tuned on roughly a
dozen photographs. They behave well there; nobody knows how they behave on snow,
concerts, or window-lit interiors.

**Architecture.** A read-only tool, `tools/corpus_report.py`:

- Input: a directory of RAWs. For each file: decode at `scene_half_size=True`, run
  `scene_tone_metrics` + `build_render_plan`, render a proxy, and record one CSV row —
  ISO, median EV, DR, sparse-emitter flag, compiled punch strength, view brightness,
  black/white endpoints, plus rendered Oklab chroma percentiles.
- Output: CSV plus a printed summary grouped by (ISO band × median-EV band) showing
  the distribution of gate values, flagging suspected misfires (e.g. punch > 0.5 with
  median < −2.5 EV).
- No pipeline changes. Threshold edits that follow from corpus findings must re-run
  the golden set (item 2) and attach the corpus summary to the commit.

---

## 5. (Parked) Pivot solver — contrast allocation for dark subjects

**Why parked.** darktable's workflow places the maximum-contrast pivot on the subject.
The brightness-preserving shifted-pivot curve is **already implemented and tested**
(`agx.curve_params(pivot_ev_offset≠0)`, `tests/test_agx_curve.py::AdaptivePivotTest`),
and `agx.compute_pivot_ev_offset` exists with a PARKED docstring. `tone.py` keeps the
offset at 0 because moving the pivot lets the calibrated EV 0 → 18 % anchor drift.

**Design.** A small 1-D solve closes the gap:

1. Build the shifted-pivot curve as today (pivot output read from the reference
   curve → subject brightness preserved).
2. Evaluate the resulting curve at scene EV 0. If |output − 0.18| > 0.005 linear,
   bisect `pivot_y_linear` within [0.02, 0.5] (each iteration = one `curve_params`
   + one `apply_curve` sample; < 20 iterations) until the EV 0 anchor holds.
3. Wire in `build_tone_compression_plan`: `pivot_ev_offset =
   compute_pivot_ev_offset(metrics.body_ev_p50, black_ev, white_ev)` for the `agx`
   and `gated` cores only. `drt.curve_params_from_plan` already threads the offset
   and enables diagonal gamma when it is non-zero.
4. Interaction rule with `view_brightness` (both target dark scenes): the pivot
   allocates **contrast**, view brightness lifts **residual brightness** — when
   |pivot_ev_offset| > 1 EV, scale the view-brightness term down (e.g. ×0.5) so the
   two do not stack into an over-lift.

**Acceptance.** Existing AdaptivePivotTest stays green; new test asserts EV 0 → 0.18
±0.005 with a −2 EV offset; golden night scenes (item 2, scene 2) show higher
subject-band slope without raising the lamp band. **Do not enable before the golden
set exists** — this deliberately changes dark-scene rendering.

---

## 6. (Parked) Mixture windows for the scene-transform prefeed

**Why parked.** Measured limit: within-scene illumination moves material
chromaticities further than camera differences do (shade-lit skin sits ~0.55 B/G away
from tungsten-lit skin in the daylight frame; the robust fitter rejects the secondary
cluster wholesale). A single Gaussian window cannot cover sun + shade + tungsten skin.

**Design (smallest step first).**

- Schema: `SceneTransformRegion` gains optional `components: [(mu, cov, weight), …]`;
  a region with components ignores its scalar mu/cov. JSON stays backward-compatible
  (absent = single-component behavior, `scene_transform.py::_region_from_dict` fills
  the single component from the legacy fields).
- Runtime (`scene_transform.py::_region_weight`): weight = **max** over component
  weights (not sum — avoids double-counting where components overlap). Von Kries
  transport applies to every component mean/cov exactly as today. Cost: K× the
  Mahalanobis evaluations inside the existing loop, K ≤ 3.
- Fitting (`tools/fit_skin_window.py`): `--components N` — k-means split of the
  trimmed samples, then per-cluster trimmed Gaussian; refuse clusters below a minimum
  sample count. Multi-DNG accumulation already exists and is the intended way to feed
  sun/shade/tungsten samples in one fit.
- Bigger alternative (local illuminant field per tile) is explicitly deferred until
  mixtures prove insufficient.

**Acceptance.** On the daylight group photo, shade-lit faces receive skin-window
coverage without the window swallowing the frame (global effective-weight coverage
stays < 25 %); the tungsten portrait's coverage is unchanged within 2 %.

---

## Suggested order

1 (CI) → 3 (debug flag, same PR) → 2 (golden set) → 4 (corpus tool) → 5 (pivot solver,
requires 2) → 6 (mixtures, independent). Delete this file when the last item lands or
is re-planned.
