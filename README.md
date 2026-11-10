# CrocoDashChecks

Checks that CrocoDash works end to end, beyond its own unit tests: real CESM runs on Derecho, performance benchmarks, and a daily check that the data sources CrocoDash reads are reachable. Reports: <https://crocodile-cesm.github.io/CrocoDashChecks/>

## Weekly CESM runs on Derecho

Every Monday, MOM_interface's regional smoke tests are built with the latest CrocoDash `main` and CESM `crocodash`, then run (see [`cesm_runs/`](cesm_runs/README.md)):

| Compset | Components | SMS_D_Ld2 |
|---|---|---|
| `CR_JRA_GLOFAS` | MOM6 + GLOFAS runoff | ![](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/CROCODILE-CESM/CrocoDashChecks/test-results/SMS_D_Ld2.CR_JRA_GLOFAS.json) |
| `CR1850MARBL_JRA_GLOFAS` | + MARBL | ![](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/CROCODILE-CESM/CrocoDashChecks/test-results/SMS_D_Ld2.CR1850MARBL_JRA_GLOFAS.json) |
| `GR_JRA_GLOFAS` | + CICE | ![](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/CROCODILE-CESM/CrocoDashChecks/test-results/SMS_D_Ld2.GR_JRA_GLOFAS.json) |
| `CWR_JRA_GLOFAS` | + WW3 | ![](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/CROCODILE-CESM/CrocoDashChecks/test-results/SMS_D_Ld2.CWR_JRA_GLOFAS.json) |
| `GWR1850MARBL_JRA_GLOFAS` | MOM6 + CICE + WW3 + MARBL + GLOFAS | ![](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/CROCODILE-CESM/CrocoDashChecks/test-results/SMS_D_Ld2.GWR1850MARBL_JRA_GLOFAS.json) |

## Benchmarks

A one-time performance snapshot for parts of the CROC ocean modeling ecosystem that don't
change commit-to-commit: xESMF/ESMF regridding (external libraries), the mom6_forge
bathymetry pipeline, and the CrocoDash OBC regrid+merge pipeline. Commit-by-commit
performance tracking for CrocoDash/mom6_forge code itself lives in those repos' own
pytest-benchmark suites, not here.

### What's benchmarked

| Suite | File(s) | Data needed | What it measures |
|---|---|---|---|
| xESMF weight generation | `xesmf/test_weights_generate.py` | None (synthetic) | `xe.Regridder()` construction time + RSS, grid→grid and grid→locstream |
| xESMF regrid application | `xesmf/test_regrid_apply.py` | None (synthetic) | `regridder(ds)` time across grid sizes, time depths, methods |
| ESMF weight generation | `esmf/test_weights_generate.py` | None (synthetic) | `esmpy.Regrid()` construction — raw ESMF, same sizes as xESMF suite |
| ESMF regrid application | `esmf/test_regrid_apply.py` | None (synthetic) | `esmpy.Regrid()(src, dst)` time — raw ESMF |
| Bathymetry pipeline | `mom6_forge/test_topo.py` | GEBCO (GLADE) | `Topo.set_from_dataset()` — GEBCO regrid + fill across domain sizes |
| OBC forcing pipeline | `crocodash/test_obc.py` | Cached GLORYS (GLADE) | REGRID + MERGE phases of `process_obc_conditions()`, varying `regrid_step` |

The xESMF/ESMF suites are pure-synthetic and marked `light`/`heavy` — the smallest
grid-size combination in each sweep is `light` (a fast smoke test), everything else is
`heavy`. `test_topo.py` and `test_obc.py` are always `heavy` — they need real GEBCO/GLORYS
data and take meaningful time even at their smallest parameter value.

Data-source health (are GLORYS/GEBCO/GLOFAS/etc. reachable?) is a separate concern —
see [Data access health](#data-access-health) below.

### Running the perf benchmarks

```bash
conda activate CrocoDash
bash scripts/configure.sh          # sanity-check the environment

bash scripts/run_benchmarks.sh                 # everything
bash scripts/run_benchmarks.sh -m light        # fast smoke test (synthetic suites only)
bash scripts/run_benchmarks.sh -k xesmf        # one suite
```

This writes `results/latest.json`. On Derecho, `qsub scripts/pbs_submit.sh` runs the full
suite (including the GEBCO/GLORYS-dependent ones) as a PBS job.

Build the report pages:

```bash
python scripts/generate_report.py         # suite pages + landing page
python scripts/generate_runoff_report.py  # runoff mapping page
open report/index.html
```

## Data access health

Whether GLORYS/GEBCO/GLOFAS/etc. are reachable and CrocoDash's access methods still work
is checked **daily**, independent of the perf benchmarks above. This runs entirely in
`.github/workflows/publish.yml`'s daily schedule — no HPC job to babysit:

```bash
# By hand; the daily CI job runs the same check in the crocontainer image:
conda activate CrocoDash
python scripts/check_data_access.py     # writes results/health.json
python scripts/generate_health_report.py
open report/health.html
```

You can also run this by hand (locally, in the `CrocoDash` env) to check status without
waiting for the schedule.

### HPC data-dependent benchmarks

Fill in paths in `benchmarks/data_config.json` to enable the tests that need real data:

| Key | Benchmark | What to put |
|---|---|---|
| `gebco_path` | `test_topo.py` | Path to `GEBCO_2024.nc` |
| `obc_hgrid_path` / `obc_bathymetry_path` / `obc_vgrid_path` | `test_obc.py` | Grid + bathymetry from an existing CrocoDash case |
| `obc_raw_data_dir` | `test_obc.py` | Pre-downloaded GLORYS OBC files, one per boundary, ISO-dated filenames |
| `obc_dates_start` / `obc_dates_end` | `test_obc.py` | Date range those raw files cover |

Tests skip gracefully (`pytest.mark.skipif` / `pytest.skip`) when the required data isn't
configured.

## CI

`.github/workflows/publish.yml` runs on push to `main`, manual dispatch, and a daily
schedule.

- On the daily schedule and manual dispatch, a `data-health` job runs inside the
  [crocontainer](https://github.com/CROCODILE-CESM/crocontainer) image (which already has
  the `CrocoDash` conda env baked in), executes `scripts/check_data_access.py` for real,
  and commits/pushes the refreshed `results/health.json`. It never runs the perf
  benchmarks themselves — those need real HPC-scale data and are run by hand (see above).
- A `publish` job then regenerates both report pages from whatever is currently committed
  under `results/` and deploys them to GitHub Pages. It always runs (even on a plain push,
  where `data-health` is skipped).

Some `validate_function` checks need credentials (Copernicus Marine, CDS) to succeed —
configure them as repo secrets (`COPERNICUSMARINE_SERVICE_USERNAME`/`_PASSWORD`,
`CDSAPI_URL`/`CDSAPI_KEY`) or those specific checks will correctly report `ok: false`.
A few others (GLORYS via RDA, CESM ocean output) read hardcoded `/glade/...` paths and can
only ever pass on GLADE — expect those to always show unhealthy from CI.

> **First-time GitHub Pages setup:** Settings → Pages → Source → GitHub Actions.

## Documentation

- [How benchmarking works](docs/how_benchmarking_works.md)
- [Adding new benchmarks](docs/adding_benchmarks.md)
