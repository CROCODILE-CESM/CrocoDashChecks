"""How long CrocoDash's open-boundary generation takes, and its peak memory, to
fit the cost to cores, domain size and source size: forcing.mom6's
ConditionsConfigurator.process_bc on the synthetic reference_ocean product, so
nothing is downloaded. (The initial condition is left out: it is one timestep,
so even a global domain bounds it.)

Each case runs process_bc twice. The first run, on every core, does GET ->
REGRID -> MERGE. The second keeps the raw files, so it skips GET, and is the one
timed: REGRID + MERGE, CrocoDash's own cost whatever the product. (GET here only
makes synthetic data; for a real product it is a download.) Both runs are forked
children of the test process, so one case's leftover heap can't count toward the
next; memory is the PSS of the whole process tree.

REGRID does the boundaries one after another, each over its 30-day slices, given
in equal runs to min(cores, slices) forked workers. Daily data on four open
boundaries of a flat 1000 m box at 0.1 degrees, centred on 200E, 0N:
  - by source resolution: a 10 degree box, 30 days, 1 worker (source points grow);
  - by domain size: a 0.25 degree source, 30 days, 1 worker (boundary cells and
    source points grow together);
  - by days: a 10 degree box, 0.25 degree source, 1 worker (slices grow);
  - by workers: 360 days, so 12 slices that 1, 2, 3, 4, 6 and 12 workers split
    evenly, on a 10 degree box at a 0.25 and a 0.05 degree source, and on an
    80 degree box (where the per-slice domain cost shows) at 0.25;
  - by location: each location matrix.yaml turns on for open_boundaries, on that
    location's own grid (across the seams, over the poles), 0.25 degree source,
    30 days, 1 worker.

In the CrocoDash env, on a compute node with at least 12 cores and ~100 GB:
    pytest performance/test_obc.py --benchmark-json=performance/obc.json
"""

import math
import os
import shutil
import sys
import traceback
from datetime import datetime, timedelta

import pytest
import xarray as xr

import matrix
from memtrack import measure_peak_rss

START = datetime(2000, 1, 1)
REGRID_STEP_DAYS = 30  # ConditionsConfigurator's default slice
BOUNDARIES = ["south", "north", "west", "east"]
COMPSET = "1850_DATM%NYF_SLND_SICE_MOM6%REGIONAL_SROF_SGLC_SWAV"
MODEL_RES_DEG = 0.1
SOURCE_RES_DEG = [0.5, 0.25, 0.1, 0.05, 0.025, 0.01]  # at a 10 degree box
SIZES_DEG = [2.5, 5.0, 10.0, 20.0, 40.0, 80.0, 160.0]  # at a 0.25 degree source
DAYS = [30, 90, 180, 360]
WORKERS = [1, 2, 3, 4, 6, 12]  # each splits 360 days' 12 slices evenly


def _box(size_deg):
    """The sweeps' domain: a square at MODEL_RES_DEG centred on 200E, 0N."""
    from mom6_forge.grid import Grid

    return Grid(
        lenx=size_deg,
        leny=size_deg,
        resolution=MODEL_RES_DEG,
        xstart=200.0 - size_deg / 2,
        ystart=-size_deg / 2,
        name="bench",
    )


def _conditions(tmp_path, monkeypatch, grid, source_res_deg, days):
    """A configured ConditionsConfigurator and the WorkflowContext it runs in."""
    from mom6_forge.topo import Topo

    from CrocoDash.forcing.base import BaseConfigurator, WorkflowContext
    from CrocoDash.forcing.mom6 import ConditionsConfigurator

    topo = Topo(grid, min_depth=10.0, git=False)
    topo.set_flat(1000.0)
    ctx = WorkflowContext(
        inputdir=tmp_path,
        supergrid_path=tmp_path / "ocean_hgrid.nc",
        vgrid_path=tmp_path / "ocean_vgrid.nc",  # only the IC reads it
        topo_path=tmp_path / "ocean_topog.nc",
        raw_data_dir=tmp_path / "raw",
        regridded_data_dir=tmp_path / "regridded",
        output_path=tmp_path / "output",
        config={},
    )
    grid.write_supergrid(str(ctx.supergrid_path))
    topo.write_topo(str(ctx.topo_path))
    for d in (ctx.raw_data_dir, ctx.regridded_data_dir, ctx.output_path):
        d.mkdir(parents=True, exist_ok=True)

    end = START + timedelta(days=days - 1)
    conditions = ConditionsConfigurator(
        start_date=START.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
        boundaries=BOUNDARIES,
        product_name="reference_ocean",
        function_name="get_reference_ocean_data",
        compset=COMPSET,
        function_args={"resolution_deg": source_res_deg},
    )
    # configure() ends by writing its user_nl_mom block into the case; there is
    # no case here, and processing only needs the parameters it sets first.
    monkeypatch.setattr(BaseConfigurator, "configure", lambda self: None)
    conditions.configure()
    return conditions, ctx


def _in_child(fn, *args):
    """Run fn(*args) in a forked child and wait for it."""
    sys.stdout.flush()
    sys.stderr.flush()
    pid = os.fork()
    if pid == 0:
        code = 1
        try:
            fn(*args)
            code = 0
        except BaseException:
            traceback.print_exc()
        finally:
            os._exit(code)
    _, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) == 0, "process_bc failed"


def _bench(
    benchmark,
    tmp_path,
    monkeypatch,
    size_deg,
    source_res_deg,
    days=30,
    workers=1,
    location=None,
):
    """Time one case on a size_deg box, or on a matrix.yaml location's grid."""
    grid = matrix.grid(location) if location else _box(size_deg)
    conditions, ctx = _conditions(tmp_path, monkeypatch, grid, source_res_deg, days)

    # First run, on every core: makes the raw files the timed run reuses.
    monkeypatch.delenv("CROCODASH_MAX_WORKERS", raising=False)
    _in_child(conditions.process_bc, ctx)
    for d in (ctx.regridded_data_dir, ctx.output_path):
        shutil.rmtree(d)  # with REGRID's cached weights
        d.mkdir()

    monkeypatch.setenv("CROCODASH_MAX_WORKERS", str(workers))
    box = {}

    def run():
        _, box["peak_mb"] = measure_peak_rss(
            _in_child, conditions.process_bc, ctx, include_children=True
        )

    benchmark.pedantic(run, rounds=1, iterations=1, warmup_rounds=0)

    # Source points: the horizontal size of each boundary's raw data.
    n_src = 0
    for b in BOUNDARIES:
        raw = sorted(ctx.raw_data_dir.glob(f"{b}_unprocessed*.nc"))[0]
        with xr.open_dataset(raw) as ds:
            n_src += ds.sizes["latitude"] * ds.sizes["longitude"]
    slices = math.ceil(days / REGRID_STEP_DAYS)
    benchmark.extra_info.update(
        location=location,
        size_deg=size_deg,
        source_res_deg=source_res_deg,
        model_res_deg=None if location else MODEL_RES_DEG,
        n_src=n_src,
        n_dst=2 * (grid.nx + grid.ny),  # boundary cells
        n_cells=grid.nx * grid.ny,  # domain cells
        days=days,
        slices=slices,
        workers=workers,
        peak_mb=box["peak_mb"],
    )


@pytest.mark.parametrize("source_res_deg", SOURCE_RES_DEG)
def test_by_source_resolution(benchmark, source_res_deg, tmp_path, monkeypatch):
    _bench(benchmark, tmp_path, monkeypatch, 10.0, source_res_deg)


@pytest.mark.parametrize("size_deg", SIZES_DEG)
def test_by_domain_size(benchmark, size_deg, tmp_path, monkeypatch):
    _bench(benchmark, tmp_path, monkeypatch, size_deg, 0.25)


@pytest.mark.parametrize("days", DAYS)
def test_by_days(benchmark, days, tmp_path, monkeypatch):
    _bench(benchmark, tmp_path, monkeypatch, 10.0, 0.25, days=days)


@pytest.mark.parametrize("workers", WORKERS)
@pytest.mark.parametrize(
    "size_deg, source_res_deg", [(10, 0.25), (10, 0.05), (80, 0.25)]
)
def test_by_workers(
    benchmark, size_deg, source_res_deg, workers, tmp_path, monkeypatch
):
    _bench(
        benchmark, tmp_path, monkeypatch, size_deg, source_res_deg, 360, workers=workers
    )


@pytest.mark.parametrize("location", matrix.locations("open_boundaries"))
def test_by_location(benchmark, location, tmp_path, monkeypatch):
    _bench(benchmark, tmp_path, monkeypatch, None, 0.25, location=location)
