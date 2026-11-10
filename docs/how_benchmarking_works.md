# How CrocoDashChecks Benchmarking Works

This document explains what actually happens when you run a benchmark — from invocation
through timing to the report pages. No ASV knowledge needed; CrocoDashChecks no longer uses it.

---

## The big picture

```
conda activate CrocoDash
bash scripts/run_benchmarks.sh
      │
      ▼
pytest discovers benchmarks/**/test_*.py
      │
      ├─ 1. Collect every test_* function, expand pytest.mark.parametrize combinations
      ├─ 2. For each parameter combination:
      │       call it with the `benchmark` fixture in-process (no subprocess spawn)
      │       → benchmark(fn) or benchmark.pedantic(fn, rounds=1, ...) times the call
      │       → benchmark.extra_info["rss_mb"] records memory, if tracked
      └─ 3. --benchmark-json=results/latest.json writes ALL results to one file,
             overwriting whatever was there before (a snapshot, not a history)
```

There's no commit-hash bookkeeping, no `environment_type`, no ASV conda-env matrix.
pytest-benchmark just runs the currently-active environment's code and times it.

**Results are a snapshot, not a timeline.** `results/latest.json` is fully overwritten by
every `run_benchmarks.sh` run. CrocoDashChecks doesn't track how these numbers change over commits
— xESMF/ESMF are external libraries that don't change with CROC's code, and the mom6_forge/
CrocoDash pipelines that *do* change per-commit are benchmarked with pytest-benchmark
commit tracking in their own repos, not here.

---

## First-time setup

```bash
conda activate CrocoDash
bash scripts/configure.sh
```

Verifies that `pytest`, `pytest-benchmark`, `CrocoDash`, `mom6_forge`, and `xesmf` are all
importable in the active environment.

---

## Parametrization

`pytest.mark.parametrize` replaces ASV's `params`/`param_names`. Stacking two
`@pytest.mark.parametrize` decorators produces their Cartesian product:

```python
@pytest.mark.parametrize("src_size,dst_size", SIZE_COMBOS)
@pytest.mark.parametrize("method", ["bilinear", "conservative"])
def test_generate_weights(benchmark, src_size, dst_size, method):
    ...
```

Each `(src_size, dst_size, method)` combination becomes its own pytest test ID and its own
row in `results/latest.json`.

---

## `light` vs `heavy`

The smallest grid-size combination in each synthetic (xESMF/ESMF) sweep is tagged
`pytest.mark.light` via `pytest.param(..., marks=...)` on that specific combination; every
other combination in the same sweep is `pytest.mark.heavy`. See
`benchmarks/common/marks.py`'s `light_or_heavy(is_light)` helper.

```bash
pytest benchmarks/ -m light        # fast smoke test — smallest synthetic combos only
pytest benchmarks/ -m heavy        # the full-size sweep — the real benchmark numbers
```

`test_topo.py` (bathymetry), `test_mapping.py` (runoff mapping) and `test_obc.py` (OBC
regrid+merge) are marked `heavy` at the whole-function level — they need real
GEBCO/GLOFAS/GLORYS data and take meaningful time even at their smallest parameter value,
so there's no fast "light" case for them.

---

## How a single benchmark runs

```
pytest calls test_generate_weights(benchmark, src_size=..., dst_size=..., method=...)
      │
      ├─ ordinary test-function setup code runs first (builds grids, etc.) — NOT timed
      │
      └─ benchmark(fn)          → calibrates reps automatically, times fn() N times
         or
         benchmark.pedantic(fn, rounds=1, iterations=1, warmup_rounds=0)
                                 → times fn() exactly once
```

Everything before the `benchmark(...)`/`benchmark.pedantic(...)` call in the test function
body is setup and isn't timed — the same role ASV's `setup()` played.

### `benchmark(fn)` vs `benchmark.pedantic(...)`

- **`benchmark(fn)`** — for cheap, synthetic benchmarks (xESMF/ESMF). pytest-benchmark
  calibrates the number of repetitions automatically to get a stable mean/stddev.
- **`benchmark.pedantic(fn, rounds=1, iterations=1, warmup_rounds=0)`** — for expensive or
  data-dependent benchmarks (GEBCO regrid, GLORYS regrid+merge). Runs `fn()` exactly once;
  repeating a multi-minute pipeline or a network call for statistical calibration would be
  wasteful.

### Skipping data-dependent benchmarks

`@pytest.mark.skipif(condition, reason=...)` replaces ASV's `raise NotImplementedError` in
`setup()`:

```python
GEBCO_AVAILABLE = bool(GEBCO_PATH) and Path(GEBCO_PATH).exists()

@pytest.mark.skipif(not GEBCO_AVAILABLE, reason="GEBCO_2024.nc not configured — GLADE only")
@pytest.mark.parametrize("domain_deg", [5, 10, 20, 40])
def test_set_from_dataset(benchmark, domain_deg, tmp_path):
    ...
```

Runtime-only checks (like the `domain_deg=40` memory guard in `test_topo.py`) call
`pytest.skip(...)` from inside the test body instead, since they depend on reading
`/sys/fs/cgroup/...` at collection time isn't reliable.

---

## Memory benchmarks

pytest-benchmark has no built-in memory measurement. `benchmarks/common/memtrack.py`
provides `measure_rss(fn, *args, **kwargs)` — a psutil RSS-delta wrapper, since ESMF's
C/Fortran heap allocations are invisible to Python's own memory introspection:

```python
from benchmarks.common.memtrack import measure_rss

def test_generate_weights(benchmark, src_size, dst_size, method):
    ...
    box = {}
    def run():
        result, box["rss_mb"] = measure_rss(xe.Regridder, src, dst, method=method, ...)
        return result
    benchmark(run)
    benchmark.extra_info["rss_mb"] = box.get("rss_mb")
```

The RSS delta is recorded once per call via a mutable closure variable, then attached to
`benchmark.extra_info` — this avoids running the (possibly expensive) function a second time
just to measure memory.

---

## Results storage

`--benchmark-json=results/latest.json` (set by `scripts/run_benchmarks.sh`) writes
pytest-benchmark's native JSON schema: machine info plus a flat `benchmarks` list of
`{name, fullname, params, stats: {mean, min, max, stddev, rounds, ...}, extra_info}`.

This file is **always overwritten**, not accumulated — commit it after a real run so the
report reflects the latest numbers:

```bash
git add results/latest.json
git commit -m "bench: <brief description>"
git push
```

---

## Report generation

`scripts/generate_report.py` reads `results/latest.json`, groups benchmarks by suite
(parsed from `fullname`) and then by test function, and renders one HTML table per function
— no charts beyond the regridding heatmap and the per-suite line charts, no computed ratios,
no hand-written prose. It writes three suite pages — `report/regridding.html` (xESMF/ESMF),
`report/crocodash.html`, `report/mom6_forge.html` — plus `report/index.html`, a landing page
linking to those three and to
`runoff_mapping.html`/`health.html`/`mom6_scaling.html`. The shared page shell (CSS,
header, cross-page nav) lives in `scripts/report_common.py`, used by all report generators.

`scripts/generate_runoff_report.py` reads the same `results/latest.json` but renders only the
runoff-mapping sweeps, onto `report/runoff_mapping.html`. It's separate because that page is
*curated*: unlike the suite pages it carries hand-written framing around the charts, since
its numbers don't mean anything on their own (wall time is nearly flat across an 800x range
of ocean grid sizes — the finding is where the cost isn't). Numbers quoted in that prose are
computed from the JSON, not typed in.

Data-access health is a separate concern with its own script and page — see
`scripts/check_data_access.py` and `scripts/generate_health_report.py` — because it runs on
its own daily cadence rather than being triggered by `run_benchmarks.sh`.

---

## CI

`.github/workflows/publish.yml` runs on push to `main`, manual dispatch, and a daily
schedule. It never runs the actual benchmarks or health checks — GitHub's runners have no
CrocoDash, GEBCO, GLORYS, or ESMF. It only regenerates the report pages
(`generate_report.py`, `generate_runoff_report.py`, `generate_health_report.py`,
`generate_scaling_report.py`) from whatever is currently committed under `results/`, then
deploys to GitHub Pages.
