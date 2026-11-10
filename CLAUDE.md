# CLAUDE.md

This file provides guidance to Claude Code when working in this repository.

## Project Overview

**CrocoDashChecks** (formerly SeaSloth) checks CrocoDash end to end. `cesm_runs/` holds the weekly Derecho CESM runs (MOM_interface's regional SMS tests built with CrocoDash, see `cesm_runs/README.md`), which publish badges to the `test-results` branch. The rest is a one-time performance snapshot for parts of the CROC ocean modeling
ecosystem that don't change commit-to-commit: xESMF/ESMF regridding (external libraries),
the mom6_forge bathymetry pipeline, and the CrocoDash OBC regrid+merge pipeline. It uses
[pytest-benchmark](https://pytest-benchmark.readthedocs.io/) and renders one static HTML
page per topic — regridding, CrocoDash, mom6_forge, data access health, MOM6 scaling — plus
an `index.html` landing page, all plain inline HTML/CSS/SVG (no charting library), no
hand-written narrative.

Commit-by-commit performance tracking for CrocoDash/mom6_forge code lives in those repos'
own pytest-benchmark suites — not here. SeaSloth (this repo's old name) previously used ASV (airspeed velocity)
for commit tracking; that's gone.

GitHub org: https://github.com/CROCODILE-CESM

## What is being benchmarked

| Suite | File(s) | Data needed | What it measures |
|---|---|---|---|
| xESMF weight generation | `xesmf/test_weights_generate.py` | None (synthetic) | `xe.Regridder()` construction time + RSS |
| xESMF regrid application | `xesmf/test_regrid_apply.py` | None (synthetic) | `regridder(ds)` time across grid sizes, time depths, methods |
| ESMF weight generation | `esmf/test_weights_generate.py` | None (synthetic) | raw `esmpy.Regrid()` construction — same sizes as xESMF |
| ESMF regrid application | `esmf/test_regrid_apply.py` | None (synthetic) | raw `esmpy.Regrid()(src, dst)` time |
| Bathymetry pipeline | `mom6_forge/test_topo.py` | GEBCO (GLADE) | `Topo.set_from_dataset()` — GEBCO regrid + fill across domain sizes |
| Runoff mapping | `mom6_forge/test_mapping.py` | GLOFAS ESMF meshes (GLADE) | `gen_rof_maps()` — nn + smoothed mapping files. Two sweeps: real ocean domains (Gulf of Mexico → Indo-Pacific) × ROF source mesh, and resolution at fixed footprint |
| OBC forcing pipeline | `crocodash/test_obc.py` | Cached GLORYS (GLADE) | REGRID + MERGE of `process_obc_conditions()`, varying `regrid_step` |

Data-source health (link/`validate_function` checks) is a **separate**, daily-run concern —
see `scripts/check_data_access.py` below, not part of the pytest-benchmark suite.

## Framework: pytest-benchmark

Every benchmark is a normal pytest test using the `benchmark` fixture. `pytest.mark.parametrize`
replaces ASV's `params`/`param_names`; `@pytest.mark.skipif` replaces ASV's
`raise NotImplementedError` in `setup()` for data-dependent tests.

Key conventions:
- `benchmark(fn)` — times `fn`, calibrating reps automatically. Use for cheap, synthetic benchmarks.
- `benchmark.pedantic(fn, rounds=1, iterations=1, warmup_rounds=0)` — times `fn` exactly
  once. Use for expensive/data-dependent benchmarks (GEBCO regrid, GLORYS regrid+merge,
  network calls) where repeating the call for statistical calibration would be wasteful or slow.
- `benchmark.extra_info["rss_mb"] = ...` — memory tracking, since pytest-benchmark has no
  built-in memory measurement. See `benchmarks/common/memtrack.py`.
- `pytest.mark.light` / `pytest.mark.heavy` — the smallest parameter combination in a
  synthetic (xESMF/ESMF) sweep is tagged `light` for a fast smoke test; everything else is
  `heavy`. `test_topo.py` and `test_obc.py` are always `heavy` — even their smallest size
  needs real GEBCO/GLORYS data and takes meaningful time. Run just the light ones with
  `pytest -m light`.

## Directory Structure

```
CrocoDashChecks/
├── pyproject.toml                        # deps + light/heavy marker registration
├── benchmarks/
│   ├── data_config.json                  # Paths to GEBCO, GLORYS, OBC config
│   ├── link_config.json                  # Product -> documentation URL, used by check_data_access.py
│   ├── common/
│   │   ├── synthetic_data.py             # make_rect_grid(), make_curvilinear_grid(), etc.
│   │   ├── config.py                     # get_path() helper to read data_config.json
│   │   ├── memtrack.py                   # measure_rss(fn, *a, **kw) -> (result, rss_mb)
│   │   └── marks.py                      # light_or_heavy(is_light) helper
│   ├── xesmf/                            # xESMF weight generation and application
│   ├── esmf/                             # Raw esmpy weight generation and application
│   ├── mom6_forge/                       # Topo.set_from_dataset(), gen_rof_maps()
│   └── crocodash/                        # OBC regrid+merge pipeline
├── results/
│   ├── latest.json                       # perf-benchmark snapshot (pytest-benchmark JSON), manual runs
│   └── health.json                       # data-access health snapshot, overwritten daily
├── scripts/
│   ├── run_benchmarks.sh                 # pytest wrapper -> results/latest.json
│   ├── merge_results.py                  # merge a partial run's JSON into results/latest.json
│   ├── report_common.py                  # shared page shell (CSS, header, cross-page nav)
│   ├── generate_report.py                # results/latest.json -> report/{regridding,crocodash,mom6_forge,index}.html
│   ├── generate_runoff_report.py         # results/latest.json -> report/runoff_mapping.html
│   ├── check_data_access.py              # link + validate_function checks -> results/health.json
│   ├── data_access.pbs                   # daily Casper job: check, push health.json + badge
│   ├── data_access_cron.sh               # cron entry point: qsubs data_access.pbs
│   ├── generate_health_report.py         # results/health.json -> report/health.html
│   ├── generate_scaling_report.py        # results/mom6_scaling.json -> report/mom6_scaling.html
│   └── pbs_submit.sh                     # PBS job for the full perf suite on Derecho/Casper
├── docs/
│   ├── how_benchmarking_works.md
│   └── adding_benchmarks.md
└── .github/workflows/publish.yml         # push to main + manual dispatch: rebuild all report pages, deploy Pages
```

## Running Benchmarks

```bash
conda activate CrocoDash

bash scripts/run_benchmarks.sh                # all perf benchmarks -> results/latest.json
bash scripts/run_benchmarks.sh -m light       # fast smoke test (synthetic suites only)
bash scripts/run_benchmarks.sh -k xesmf       # one suite

python scripts/generate_report.py             # -> report/{regridding,crocodash,mom6_forge,index}.html
python scripts/generate_runoff_report.py      # -> report/runoff_mapping.html

# On Derecho — PBS job for the full suite (needs GEBCO/GLORYS data)
qsub scripts/pbs_submit.sh
```

### Partial runs: merge, don't overwrite

`run_benchmarks.sh` passes `--benchmark-json=results/latest.json`, so **any partial run
replaces the whole snapshot** and silently drops every suite that wasn't part of it. Suites
have incompatible requirements (the 40° GEBCO sweep needs ~90 GB; the runoff-mapping sweep
needs a different conda env), so refreshing one suite means writing to a scratch file and
merging:

```bash
pytest benchmarks/mom6_forge/test_mapping.py --benchmark-json=/tmp/rof.json -v
python scripts/merge_results.py /tmp/rof.json     # -> results/latest.json
python scripts/generate_runoff_report.py
```

`merge_results.py` keys on `fullname` — incoming entries replace same-named ones, everything
else is untouched. After reworking a `@parametrize`, add `--prune-stale` so the old parameter
ids are dropped instead of lingering in the snapshot and being charted next to the new ones;
don't combine it with `-k`, since it would delete the deselected cases' results.

Since a merged snapshot spans multiple sessions, its top-level
`machine_info`/`datetime` no longer cover every entry, so each merged benchmark carries its
own `extra_info["run_datetime"]`/`["run_node"]`.

### Runoff mapping: keep every domain clear of the 0/360 seam

`test_gen_rof_maps_domain` walks an ascending ladder of destination sizes, ~4x per
rung, all against the production ROF mesh. Measured:

| Domain | Cells @ 1/12° | Time |
|---|---|---|
| 1° box | 144 | 77.7 s |
| 2° box | 576 | 73.7 s |
| 4° box | 2.3K | 76.5 s |
| 8° box | 9.2K | 74.2 s |
| Gulf of Mexico | 34K | 80.7 s |
| Caribbean | 116K | 78.9 s |
| North Atlantic | 576K | 105.7 s |
| Indo-Pacific | 2.42M | 187.2 s |

Cost is flat to ~116K cells (805x more cells for 1.02x the time) and then rises
mildly — 2.4M cells is ~2.4x the 144-cell box. The dominant term at the small end is
the fixed source-mesh read/re-write, ~2.2 GB per source-domain field into both output
files; the destination grid only starts to matter at basin scale. Peak RSS is ~12.5–13.4
GB up to the Caribbean, rising to 15.8 GB at 2.4M cells.

**This suite briefly claimed a size cliff above ~150K cells. That was wrong**, and the
reason is a real `mom6_forge` bug worth knowing about. The `north_atlantic` box was
`(xstart=280, lenx=80)` and 280 + 80 = 360, so its eastern edge sat on the periodic
seam. `_get_mesh_bbox()` normalizes longitudes into [0, 360), so the 601 nodes at
exactly 360 become 0, and its naive `min()`/`max()` then returns a **near-global**
longitude bbox (`0.00 .. 359.92`) instead of `280 .. 360`. That makes
`generate_ESMF_map_via_xesmf`'s `map_overlap` masking a no-op in longitude, so the
regrid runs against the entire global 20–70°N band rather than the domain's own 80°
window — and does not finish in over an hour. Shifted 5° west, the identical
576K-cell case takes 106 s.

Fixed in `mom6_forge` (PR #125). `_get_mesh_bbox()` now delegates to `_lon_bbox()`,
which returns the interval outside the largest angular *gap* between successive
longitudes — so a seam-crossing domain gets an honestly wrapped range
(`lon_min > lon_max`) rather than a near-global one — and `_lon_outside()` is the
matching membership test that `map_overlap` consumes. The exact box that hung, lon
280..360 at 576K cells, now reports an 80.00° bbox and finishes in 67.7 s. (Faster than
the 105.7 s north_atlantic rung above, but not inconsistent with it: the two 80° windows
sit over different river density — 275..355 carries the Mississippi/Gulf outflow,
280..360 trades that for the quieter east Atlantic.) The same change fixed a quieter
case nobody had noticed: a domain spanning -10..10 previously reported a 350° bbox.

`DOMAINS` still asserts at import that no box touches the seam. Keep that guard — not
because the bug is live, but because the ladder above was measured off-seam and should
stay comparable, and because the suite can be run against an older `mom6_forge` where
the failure mode is silent (no error, no memory growth, ~1 GB RSS, one core pinned) and
a reintroduced seam box just looks like a hang.

### The runoff-mapping suite needs the `mom6_forge` env

`benchmarks/mom6_forge/test_mapping.py` must run in the **`mom6_forge`** conda env, not
`CrocoDash`:

```bash
conda run -n mom6_forge pytest benchmarks/mom6_forge/test_mapping.py --benchmark-json=/tmp/rof.json -v
```

The `CrocoDash` env imports its own nested mom6_forge checkout
(`CrocoDash/CrocoDash/visualCaseGen/external/mom6_forge/`), which is on a different branch
and lacks the mapping write-path fix from mom6_forge PR #125 until CrocoDash bumps its
pointer. Without that fix a single
run against the production mesh takes ~36 min and peaks near 13 GB, and on pre-fix `main` it OOMs outright.
The test detects this and skips rather than burning hours — so a `CrocoDash`-env run reports
the suite as skipped, not as fast.

Data access health runs separately, daily on GLADE: a crontab line on `cron.hpc.ucar.edu`
runs `scripts/data_access_cron.sh`, which qsubs `scripts/data_access.pbs` to Casper. The job
pushes `results/health.json` to `main` and a `data_access.json` badge to `test-results`,
both through `cesm_runs/publish_badges.sh`. Each access method is checked in its own process,
`VALIDATE_WORKERS` at a time; one still running after `VALIDATE_TIMEOUT` is killed with its
process group, its temp dir (and any partial download) removed, and a failing check records
its last error line as `detail` in `health.json`. Run it by hand the same way locally:

```bash
python scripts/check_data_access.py           # -> results/health.json
python scripts/generate_health_report.py      # -> report/health.html
```

## data_config.json

Keys that need to be set before HPC-dependent benchmarks will run:

| Key | Used by | Description |
|---|---|---|
| `gebco_path` | `test_topo.py` | Path to GEBCO_2024.nc |
| `rof_esmf_mesh_global_path` | `test_mapping.py` | Registered production global GLOFAS ESMF mesh (21.6M elements) — what a real CESM case gets as `ROF_DOMAIN_MESH` |
| `obc_hgrid_path` / `obc_bathymetry_path` / `obc_vgrid_path` | `test_obc.py` | Grid + bathymetry from an existing CrocoDash case |
| `obc_raw_data_dir` | `test_obc.py` | Directory of pre-downloaded GLORYS OBC files, one per boundary, named `{boundary}_unprocessed.{start}_{end}.nc` with ISO dates |
| `obc_dates_start` / `obc_dates_end` | `test_obc.py` | Date range those raw files cover |

Tests using these paths skip via `pytest.mark.skipif`/`pytest.skip()` when the path is unset
or missing.

## Memory Benchmarks

Use `benchmarks/common/memtrack.py`'s `measure_rss(fn, *args, **kwargs)` — not ASV's
`track_rss_mb` convention. It returns `(result, rss_delta_mb)`; stash the delta into
`benchmark.extra_info["rss_mb"]`. This exists because ESMF performs large C/Fortran heap
allocations invisible to Python's `sys.getsizeof`/`tracemalloc`.

## Synthetic Data

Use helpers from `benchmarks/common/synthetic_data.py` — do not create grids inline.

| Function | Returns | Use for |
|---|---|---|
| `make_rect_grid(nlon, nlat)` | 1D lon/lat xr.Dataset with bounds | xESMF source |
| `make_curvilinear_grid(nlon, nlat)` | 2D lon/lat xr.Dataset with bounds | xESMF destination |
| `make_locstream_grid(n)` | 1D ncells xr.Dataset | OBC boundary (locstream_out=True) |
| `make_data_variable(grid, ntime, nvars)` | grid + data variables | Anything needing data to regrid |

For ESMF direct benchmarks use `_make_esmpy_grid(nlon, nlat)` defined inline in the
benchmark file — not the xarray helpers.

## Report generators

All plain stdlib (`json` + f-strings) — no matplotlib, no numpy, no image generation. Every
generator shares one page shell — CSS, header, cross-page nav bar — from
`scripts/report_common.py`, so adding or renaming a report page means updating `NAV_PAGES`
in one place rather than five nav bars by hand.

`scripts/generate_report.py` groups `results/latest.json`'s benchmarks by suite (parsed from
`fullname`) then by test function, and writes three suite pages:
- `report/regridding.html` — the six xESMF/ESMF weight-generation/apply benchmarks
  consolidated into one heatmap section (source size × destination size → time, inline HTML
  table + a shared log-scale color legend, sequential-blue ramp from the dataviz palette),
  no separate detail tables, the heatmap is the whole story.
- `report/mom6_forge.html` — `test_topo`'s `test_set_from_dataset` gets a small inline-SVG
  line chart (domain size → time, log-scale y-axis, direct value labels) since it's a
  natural sweep.
- `report/crocodash.html` — `test_obc`'s `test_regrid_and_merge` gets the same style of
  line chart (time vs. regrid_step).

`scripts/generate_dashboard.py` writes the landing page, `report/index.html`: a dashboard
of where each check stands. Status tiles for the weekly CESM runs, data access and the
performance snapshot; the CESM runs' per-phase table from `results/cesm_runs.json` (which
`cesm_runs/run_mom_tests.py` writes to the `test-results` branch, and `publish.yml` fetches
before building); data access grouped by product from `results/health.json`; and cards
linking the performance pages. Status colors (good/warning/critical) mark state only, always
beside a text label. A check older than `STALE_DAYS` gets a "Stale" chip, since a schedule
that stops running fails silently otherwise. Every number on it comes from the JSON.

`test_mapping`'s two sweeps are *not* on the mom6_forge page — they have their own page
(below). `TESTS_ON_OTHER_PAGES` in `generate_report.py` is what keeps them from also
appearing there as a fallback table; add to it whenever a test moves onto a curated page.

`scripts/generate_runoff_report.py` writes `report/runoff_mapping.html` from the same
`results/latest.json`, importing its two chart builders from `generate_report.py` so the two
files can't disagree about how a rung is named. Both charts are drawn by `_multiline_svg()`
(log axis, HTML legend, two-line x labels): `test_gen_rof_maps_domain` (the destination-size
ladder) and `test_gen_rof_maps_resolution` (fixed footprint, increasing resolution). There's
a single series — the production ROF mesh — and the legend carries its element count, since
that's what sets the absolute numbers. x-axis cell counts and the legend label come from each
benchmark's `extra_info` (`n_src`/`n_dst`/`domain`) rather than being recomputed in the
generator, so a chart can't drift from the parameters the benchmark actually ran. A rung with
no data yet renders as a **gap** (`_multiline_svg` takes `None` values) rather than shifting
the remaining points.

Both ROF charts pass `_multiline_svg(..., y_span_decades=1)`. Auto-scaling a log axis to the
data's own range is right for a sweep spanning orders of magnitude, but it *lies* about a flat
one — fit a 1.02× spread to the full plot height and run-to-run noise renders as a mountain
range, saying the opposite of what the page says. Pinning the axis to one decade makes a flat
curve look flat. Keep this in mind before reusing `_multiline_svg` for anything else nearly
flat.

Any test function not covered by a chart still gets a plain table (params, mean, min, max,
rss). `scripts/generate_health_report.py` renders `results/health.json`'s
`link_checks`/`validate_checks` lists as two small tables on `report/health.html`.
`scripts/generate_scaling_report.py` renders `results/mom6_scaling.json` as a line chart +
table on `report/mom6_scaling.html`.

**Where prose is allowed.** The auto-generated suite pages (`regridding`, `crocodash`,
`mom6_forge`) stay numbers-only: no cross-benchmark ratios, no narrative. If you're tempted
to add narrative there, don't — that's the complexity the original rewrite removed. The two
curated pages, `mom6_scaling.html` and `runoff_mapping.html`, do carry hand-written framing,
because their numbers are meaningless without it (a runoff timing of 80 s reads as slow until
you know it barely moves across an 800× range of ocean grids). The rule for those: any
*number* inside the prose is computed from the JSON, never typed in — see
`generate_runoff_report.py`'s `_spread_sentence()`, which derives the headline ratio from the
data so it can't go stale when the sweep is re-run.

Every generator also calls `report_common.publish_results_json()`, which copies the
`results/*.json` it just rendered into `report/` next to the HTML (e.g. `results/health.json`
-> `report/health.json`). This makes the underlying data fetchable at a stable Pages URL
(`.../health.json`, `.../latest.json`, `.../mom6_scaling.json`) instead of only living in the
git repo — the point being that other tools (e.g. a CrocoDash helper checking "is glorys
healthy right now?") can `GET` it directly rather than scraping HTML. Each rendered page links
to its source JSON via a "Raw data (JSON)" link in the header, driven by the third element of
each `NAV_PAGES` tuple in `scripts/report_common.py`.

## CI

`.github/workflows/publish.yml` triggers on push to `main` (including the daily health push
from GLADE) and `workflow_dispatch`.

- **`publish`**: regenerates all report pages from whatever is currently
  committed under `results/` and deploys to GitHub Pages. It never runs the perf
  benchmarks — those need real HPC-scale GEBCO/GLORYS data and stay a manual/PBS thing.

## Linting

Use black before committing:
```bash
black benchmarks/ scripts/
```
