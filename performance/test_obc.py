"""How long CrocoDash's open-boundary generation takes, and its peak memory:
forcing.mom6.ConditionsConfigurator.process_bc (GET -> REGRID -> MERGE), on the
synthetic reference_ocean product, so nothing is downloaded and the cost is
CrocoDash's own. (The initial condition is left out: it is one timestep, so even
a global domain bounds it.)

Daily data on four open boundaries of a flat 1000 m box at 0.1 degrees:
  - by source resolution, a month at a 10 degree box: more source points per
    boundary point;
  - by domain size, a month at a 0.25 degree source: both grow at a fixed ratio;
  - by worker count, a year at a 10 degree box and 0.25 degree source.

REGRID does the boundaries one after another, each over its 30-day slices with
min(cores, slices) forked workers, so a month uses at most two; the year is
what shows how more cores help.

In the CrocoDash env, on a compute node with at least 12 cores:
    pytest performance/test_obc.py --benchmark-json=performance/obc.json
"""

import pytest
import xarray as xr

from memtrack import measure_peak_rss

MONTH, YEAR = ("20000101", "20000131"), ("20000101", "20001231")
REGRID_STEP_DAYS = 30  # ConditionsConfigurator's default slice
BOUNDARIES = ["south", "north", "west", "east"]
COMPSET = "1850_DATM%NYF_SLND_SICE_MOM6%REGIONAL_SROF_SGLC_SWAV"
MODEL_RES_DEG = 0.1
SOURCE_RES_DEG = [0.5, 0.25, 0.1, 0.05, 0.025]  # at a 10 degree box
SIZES_DEG = [2.5, 5.0, 10.0, 20.0, 40.0]  # at a 0.25 degree source
WORKERS = [1, 2, 4, 8, 12]  # a year has 13 thirty-day slices


def _conditions(tmp_path, monkeypatch, size_deg, source_res_deg, dates):
    """A configured ConditionsConfigurator and the WorkflowContext it runs in."""
    from mom6_forge.grid import Grid
    from mom6_forge.topo import Topo

    from CrocoDash.forcing.base import BaseConfigurator, WorkflowContext
    from CrocoDash.forcing.mom6 import ConditionsConfigurator

    grid = Grid(
        lenx=size_deg,
        leny=size_deg,
        resolution=MODEL_RES_DEG,
        xstart=300.0,
        ystart=20.0,
        name="bench",
    )
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

    conditions = ConditionsConfigurator(
        start_date=dates[0],
        end_date=dates[1],
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
    return conditions, ctx, grid


def _bench(benchmark, tmp_path, monkeypatch, size_deg, source_res_deg, dates=MONTH):
    from datetime import datetime

    from CrocoDash.forcing.obc import _make_date_pairs, available_cpus

    conditions, ctx, grid = _conditions(
        tmp_path, monkeypatch, size_deg, source_res_deg, dates
    )
    start, end = (datetime.strptime(d, "%Y%m%d") for d in dates)
    slices = _make_date_pairs(start, end, REGRID_STEP_DAYS)
    box = {}

    def run():
        _, box["peak_rss_mb"] = measure_peak_rss(
            conditions.process_bc, ctx, include_children=True
        )

    benchmark.pedantic(run, rounds=1, iterations=1, warmup_rounds=0)
    # Source points: the horizontal size of each boundary's raw data.
    n_src = 0
    for b in BOUNDARIES:
        raw = sorted(ctx.raw_data_dir.glob(f"{b}_unprocessed*.nc"))[0]
        with xr.open_dataset(raw) as ds:
            n_src += ds.sizes["latitude"] * ds.sizes["longitude"]
    benchmark.extra_info.update(
        size_deg=size_deg,
        source_res_deg=source_res_deg,
        model_res_deg=MODEL_RES_DEG,
        n_src=n_src,
        n_dst=2 * (grid.nx + grid.ny),  # boundary cells
        days=(end - start).days + 1,
        regrid_workers=min(available_cpus(), len(slices)),  # per boundary
        peak_rss_mb=box["peak_rss_mb"],
    )


@pytest.mark.parametrize("source_res_deg", SOURCE_RES_DEG)
def test_by_source_resolution(benchmark, source_res_deg, tmp_path, monkeypatch):
    _bench(benchmark, tmp_path, monkeypatch, 10.0, source_res_deg)


@pytest.mark.parametrize("size_deg", SIZES_DEG)
def test_by_domain_size(benchmark, size_deg, tmp_path, monkeypatch):
    _bench(benchmark, tmp_path, monkeypatch, size_deg, 0.25)


@pytest.mark.parametrize("workers", WORKERS)
def test_by_workers(benchmark, workers, tmp_path, monkeypatch):
    monkeypatch.setenv("CROCODASH_MAX_WORKERS", str(workers))
    _bench(benchmark, tmp_path, monkeypatch, 10.0, 0.25, dates=YEAR)
    benchmark.extra_info["workers"] = workers
