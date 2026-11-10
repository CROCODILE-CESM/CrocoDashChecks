# Adding New Benchmarks to CrocoDashChecks

## Which file to edit

| What you're benchmarking | File |
|---|---|
| xESMF weight generation | `benchmarks/xesmf/test_weights_generate.py` |
| xESMF regrid application | `benchmarks/xesmf/test_regrid_apply.py` |
| Raw ESMF weight generation | `benchmarks/esmf/test_weights_generate.py` |
| Raw ESMF regrid application | `benchmarks/esmf/test_regrid_apply.py` |
| mom6_forge bathymetry pipeline | `benchmarks/mom6_forge/test_topo.py` |
| mom6_forge runoff mapping (`gen_rof_maps`) | `benchmarks/mom6_forge/test_mapping.py` |
| CrocoDash OBC regrid+merge pipeline | `benchmarks/crocodash/test_obc.py` |

Remember: CrocoDashChecks is for one-time/stable-reference benchmarks only (external libraries,
or CROC pipelines that need a reference number but aren't worth commit-by-commit tracking).
If you're adding a benchmark to track CrocoDash/mom6_forge code performance over time, it
belongs in that repo's own pytest-benchmark suite instead.

## Benchmark function anatomy

```python
import pytest

from benchmarks.common.memtrack import measure_rss

@pytest.mark.parametrize("grid_size", [100, 300, 600])
@pytest.mark.parametrize("method", ["bilinear", "conservative"])
def test_my_operation(benchmark, grid_size, method):
    from mom6_forge.grid import Grid

    grid = Grid(lenx=10.0, leny=10.0, nx=grid_size, ny=grid_size)  # setup — not timed
    box = {}

    def run():
        result, box["rss_mb"] = measure_rss(do_the_thing, grid, method=method)
        return result

    benchmark(run)                              # times run(), calibrating reps automatically
    benchmark.extra_info["rss_mb"] = box.get("rss_mb")
```

For expensive or data-dependent operations (multi-minute pipelines, network calls), use
`benchmark.pedantic(run, rounds=1, iterations=1, warmup_rounds=0)` instead of `benchmark(run)`
so the call happens exactly once.

## Importing mom6_forge and CrocoDash

Both are installed in the `CrocoDash` conda env in editable mode — just `import` them
directly, no `sys.path` manipulation needed. Put the import inside the test function (not at
module top level) if you want a missing package to only break that one test rather than
failing collection of the whole file.

## Data-dependent benchmarks

Read paths from `benchmarks/data_config.json` via the shared helper, and skip when the data
isn't there:

```python
from pathlib import Path
import pytest
from benchmarks.common.config import get_path

GEBCO_PATH = get_path("gebco_path")
GEBCO_AVAILABLE = bool(GEBCO_PATH) and Path(GEBCO_PATH).exists()

@pytest.mark.skipif(not GEBCO_AVAILABLE, reason="GEBCO_2024.nc not configured — GLADE only")
@pytest.mark.parametrize("domain_deg", [5, 10, 20, 40])
def test_set_from_dataset(benchmark, domain_deg, tmp_path):
    ...
```

Currently configured `data_config.json` keys:

| Key | Used by |
|---|---|
| `gebco_path` | `test_topo.py` |
| `rof_esmf_mesh_global_path` | `test_mapping.py` |
| `obc_hgrid_path` / `obc_bathymetry_path` / `obc_vgrid_path` | `test_obc.py` |
| `obc_raw_data_dir` | `test_obc.py` |
| `obc_dates_start` / `obc_dates_end` | `test_obc.py` |

## Synthetic data

Use helpers from `benchmarks/common/synthetic_data.py` — do not create grids inline:

| Function | Returns | Use for |
|---|---|---|
| `make_rect_grid(nlon, nlat)` | xr.Dataset with 1D lon/lat + bounds | xESMF source |
| `make_curvilinear_grid(nlon, nlat)` | xr.Dataset with 2D lon/lat + bounds | xESMF destination |
| `make_locstream_grid(n)` | xr.Dataset with 1D ncells | OBC boundary (locstream_out=True) |
| `make_data_variable(grid, ntime, nvars)` | grid + data vars | Anything needing actual data to regrid |

For raw-ESMF benchmarks, use the `_make_esmpy_grid(nlon, nlat)` helper defined inline in
`benchmarks/esmf/test_*.py` — not the xarray helpers, since esmpy doesn't use xarray.

## `light` vs `heavy`

If your benchmark sweeps parameter sizes and is cheap/synthetic (no real data, no network),
tag its smallest combination `light` so it can be used as a fast smoke test:

```python
from benchmarks.common.marks import light_or_heavy

SIZES = [100, 300, 600]

@pytest.mark.parametrize(
    "grid_size",
    [pytest.param(s, marks=light_or_heavy(s == SIZES[0])) for s in SIZES],
)
def test_my_operation(benchmark, grid_size):
    ...
```

If your benchmark needs real data (GEBCO, GLORYS, network access) and takes meaningful time
even at its smallest parameter value, mark the whole function `heavy` instead — don't bother
picking out a "light" case, there isn't a fast one:

```python
@pytest.mark.heavy
@pytest.mark.parametrize("step_days", [5, 15, 30])
def test_regrid_and_merge(benchmark, step_days, tmp_path):
    ...
```

## Running your new benchmark

```bash
conda activate CrocoDash

bash scripts/run_benchmarks.sh -k test_my_operation   # just this benchmark
bash scripts/run_benchmarks.sh -m light               # smoke test across all light cases
bash scripts/run_benchmarks.sh                         # everything -> results/latest.json

python scripts/generate_report.py                      # -> report/{regridding,crocodash,mom6_forge,index}.html
python scripts/generate_runoff_report.py               # -> report/runoff_mapping.html
```

## Committing results

`results/latest.json` is a snapshot — it's overwritten every run, not accumulated. Commit it
after a real (non-`-k`, non-`-m light`) run so the report reflects the latest numbers:

```bash
git add results/latest.json
git commit -m "bench: add test_my_operation"
git push
```
