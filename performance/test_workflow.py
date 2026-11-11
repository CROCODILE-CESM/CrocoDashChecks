"""CrocoDash's workflow on every grid in matrix.yaml, timed: an integration test
and a benchmark in one.

For each row of matrix.yaml:
  1. test_grid builds its grid, bathymetry and vertical grid from its CrocoDash
     case config (case.yaml plus the row) with CrocoDash's own builders, as
     `crocodash create` does, and writes the files a case gets: supergrid,
     topography, vertical grid and ESMF mesh. It checks for missing depths and
     that there is some ocean. Each grid is built once; the forcings reuse it.
  2. test_bc and test_runoff run each forcing the row turns on, through
     CrocoDash's own configurators (configure, then process), as `crocodash
     process --bc` or `--runoff` would, but without a CESM case. A forcing on a
     grid that failed to build is skipped.

Then the sweeps vary what isn't a grid, on a few rows, for the Performance
page's fits: open boundaries by source resolution, days and workers, and
runoff by smoothing radius.

Every step runs in a forked child, so one case's leftover heap can't count
toward the next; its memory is the peak PSS of the whole process tree.

Open boundaries use CrocoDash's synthetic reference_ocean (case.yaml), so
nothing is downloaded. Each case runs process_bc twice: first on every core,
which makes the raw data; then, raw data kept and regridded data cleared, the
timed run: REGRID + MERGE, CrocoDash's own cost whatever the product. REGRID
does the boundaries one after another, each over its 30-day slices, given in
equal runs to min(workers, slices) forked workers.

Runoff maps GLOFAS (the mesh CESM's DROF reads, from case.yaml) onto the row's
ESMF mesh: nearest neighbour, then smoothed over rmax.

In the CrocoDash env, after `source crocodash_main.sh`, on a node with 16 cores
and 180 GB (performance/run.pbs does this):
    pytest performance/test_workflow.py \\
        --benchmark-json=performance/workflow.json --junitxml=performance/workflow.xml
"""

import json
import math
import os
import shutil
import subprocess
import sys
import threading
import traceback
from datetime import datetime, timedelta

import numpy as np
import psutil
import pytest
import xarray as xr

import matrix

# Compsets for the configurators: open boundaries need a regional MOM6,
# runoff mapping a data runoff model.
BC_COMPSET = "1850_DATM%NYF_SLND_SICE_MOM6%REGIONAL_SROF_SGLC_SWAV"
ROF_COMPSET = "1850_DATM%JRA_SLND_SICE_MOM6%REGIONAL_DROF%GLOFAS_SGLC_SWAV"
BOUNDARIES = ["south", "north", "west", "east"]
REGRID_STEP_DAYS = 30  # ConditionsConfigurator's slice

# Each row's own case. rmax = 20 km is the CrocIndoPacific_112 production value;
# fold = rmax keeps the smoothing kernel's shape the same at every radius.
SOURCE_RES_DEG, DAYS, WORKERS = 0.25, 30, 1
RMAX_KM = 20

# The sweeps, on rows matrix.yaml must turn the forcing on for.
BC_SWEEP_ROW = "pacific_10deg"
BC_SOURCE_RES_DEG = [0.5, 0.25, 0.1, 0.05, 0.025, 0.01]
BC_DAYS = [30, 90, 180, 360]
# 360 days = 12 slices, which these worker counts split evenly. The 80° box is
# where the per-slice domain cost shows.
BC_WORKER_SETS = [
    ("pacific_10deg", 0.25),
    ("pacific_10deg", 0.05),
    ("pacific_80deg", 0.25),
]
BC_WORKERS = [1, 2, 3, 4, 6, 12]
# indo_pacific at rmax 80 has ~1.7e9 weights (77% of 2^31) and peaks near 90 GB;
# rmax 100 would pass 2^31, so the sweep stops at 80.
RUNOFF_SWEEP_ROWS = ["gulf_of_mexico", "north_atlantic", "indo_pacific"]
RUNOFF_RMAX_KM = [10, 20, 40, 80]


@pytest.fixture(scope="session", autouse=True)
def _crocodash_tested(record_testsuite_property):
    """Record in workflow.xml which CrocoDash this run tested: the clone
    crocodash_main.sh made."""
    src = os.environ.get("CROCODASH_SRC")
    if src:
        for name, arg in (("branch", "--abbrev-ref"), ("commit", "--short")):
            git = ["git", "-C", src, "rev-parse", arg, "HEAD"]
            value = subprocess.run(git, capture_output=True, text=True).stdout.strip()
            record_testsuite_property(f"crocodash_{name}", value)


def _bc_sweep():
    """(row, source resolution, days, workers) for each sweep case that isn't a row's own."""
    cases = [(BC_SWEEP_ROW, s, DAYS, WORKERS) for s in BC_SOURCE_RES_DEG]
    cases += [(BC_SWEEP_ROW, SOURCE_RES_DEG, d, WORKERS) for d in BC_DAYS]
    cases += [(row, s, 360, w) for row, s in BC_WORKER_SETS for w in BC_WORKERS]
    on = matrix.rows("bc")
    own = {(row, SOURCE_RES_DEG, DAYS, WORKERS) for row in on}
    return [c for c in dict.fromkeys(cases) if c[0] in on and c not in own]


def _runoff_sweep():
    on = matrix.rows("runoff")
    return [
        (row, rmax)
        for row in RUNOFF_SWEEP_ROWS
        for rmax in RUNOFF_RMAX_KM
        if row in on and rmax != RMAX_KM
    ]


# --- running and measuring a step -------------------------------------------


def measure_peak_rss(fn, *args):
    """Call fn(*args), returning (result, peak MB): the highest memory this
    process and its children reached during the call, sampled every 0.05 s.

    PSS rather than RSS: a forked child shares its parent's pages
    copy-on-write, and RSS would count each shared page once per process. The
    peak includes what this process already held, so it bounds the step's own
    footprint from above."""
    proc = psutil.Process(os.getpid())

    def pss():
        total = 0
        for p in [proc] + proc.children(recursive=True):
            try:
                total += p.memory_full_info().pss
            except psutil.Error:  # a child can exit between listing and reading
                pass
        return total

    peak = pss()
    done = threading.Event()

    def watch():
        nonlocal peak
        while not done.wait(0.05):
            try:
                peak = max(peak, pss())
            except psutil.Error:  # introspection can race at teardown
                return

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    try:
        result = fn(*args)
        peak = max(peak, pss())
    finally:
        done.set()
        watcher.join(timeout=1.0)
    return result, peak / 1024**2


def _in_child(fn, *args):
    """Run fn(*args) in a forked child; if it fails, raise its last error line
    here (and print its traceback), so the results say why."""
    sys.stdout.flush()
    sys.stderr.flush()
    read_end, write_end = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(read_end)
        code = 0
        try:
            fn(*args)
        except BaseException:
            code = 1
            os.write(write_end, traceback.format_exc().encode())
        finally:
            os._exit(code)
    os.close(write_end)
    with os.fdopen(read_end) as pipe:
        error = pipe.read()
    _, status = os.waitpid(pid, 0)
    code = os.waitstatus_to_exitcode(status)
    if code != 0:
        print(error, file=sys.stderr)
        lines = error.strip().splitlines()
        raise RuntimeError(
            lines[-1] if lines else f"killed by signal {-code} (out of memory?)"
        )


def _timed(benchmark, fn, *args):
    """Time one run of fn(*args) in a forked child; return its peak memory (MB)."""
    box = {}

    def run():
        _, box["peak_mb"] = measure_peak_rss(_in_child, fn, *args)

    benchmark.pedantic(run, rounds=1, iterations=1, warmup_rounds=0)
    return box["peak_mb"]


# --- the grid ---------------------------------------------------------------

_GRIDS = {}  # row -> the directory its grid files are in, or why it failed to build


def _build_grid(row, workdir):
    """Build a row's grid, bathymetry and vertical grid from its case config
    with CrocoDash's builders, and write the files a case gets."""
    from CrocoDash import recipe

    os.chdir(workdir)
    cfg = matrix.config(row, workdir)
    grid = recipe.build_grid(cfg["grid"])
    topo = recipe.build_topo(cfg["topo"], grid)
    vgrid = recipe.build_vgrid(cfg["vgrid"], topo)
    grid.write_supergrid(str(workdir / "ocean_hgrid.nc"))
    topo.write_topo(str(workdir / "ocean_topog.nc"))
    vgrid.write(str(workdir / "ocean_vgrid.nc"))
    topo.write_esmf_mesh(str(workdir / "ocean_mesh.nc"))

    depth = np.asarray(topo.depth)
    ocean = depth > 0
    area_km2 = np.asarray(grid.tarea) / 1e6
    stats = {
        "nx": int(grid.nx),
        "ny": int(grid.ny),
        "n_cells": int(depth.size),
        "ocean_cells": int(ocean.sum()),
        "missing_depths": int(np.isnan(depth).sum()),
        "ocean_cell_km2": float(area_km2[ocean].mean()) if ocean.any() else None,
        "bathymetry": os.path.basename(
            cfg["topo"]["source"].get("bathymetry_path", "")
        ),
    }
    (workdir / "grid.json").write_text(json.dumps(stats))


def _grid(row, tmp_path_factory):
    """A row's grid directory, built once per session (untimed if test_grid
    didn't run first); skips the calling test if the grid failed to build."""
    if row not in _GRIDS:
        workdir = tmp_path_factory.mktemp(row)
        try:
            _in_child(_build_grid, row, workdir)
            _GRIDS[row] = workdir
        except RuntimeError as error:
            _GRIDS[row] = error
    if isinstance(_GRIDS[row], Exception):
        pytest.skip(f"its grid failed to build: {_GRIDS[row]}")
    return _GRIDS[row]


def _grid_stats(grid_dir):
    return json.loads((grid_dir / "grid.json").read_text())


def _context(grid_dir, run_dir):
    """The WorkflowContext a forcing's process step gets: the row's grid files,
    and this case's own data directories."""
    from CrocoDash.forcing.base import WorkflowContext

    ctx = WorkflowContext(
        inputdir=run_dir,
        supergrid_path=grid_dir / "ocean_hgrid.nc",
        vgrid_path=grid_dir / "ocean_vgrid.nc",
        topo_path=grid_dir / "ocean_topog.nc",
        raw_data_dir=run_dir / "raw",
        regridded_data_dir=run_dir / "regridded",
        output_path=run_dir / "output",
        config={},
    )
    for d in (ctx.raw_data_dir, ctx.regridded_data_dir, ctx.output_path):
        d.mkdir(parents=True, exist_ok=True)
    return ctx


def _no_case(monkeypatch):
    """A configurator's configure() ends by writing its settings into the CESM
    case; there is none here, and processing needs only what it sets first."""
    from CrocoDash.forcing.base import BaseConfigurator

    monkeypatch.setattr(BaseConfigurator, "configure", lambda self: None)


@pytest.mark.parametrize("row", matrix.rows())
def test_grid(benchmark, row, tmp_path_factory):
    workdir = tmp_path_factory.mktemp(row)
    try:
        peak_mb = _timed(benchmark, _build_grid, row, workdir)
    except RuntimeError as error:
        _GRIDS[row] = error
        raise
    _GRIDS[row] = workdir
    stats = _grid_stats(workdir)
    spec = matrix.GRIDS[row]["grid"]
    benchmark.extra_info.update(
        row=row,
        area_deg2=None if matrix.is_polar(row) else spec["lenx"] * spec["leny"],
        peak_mb=peak_mb,
        **stats,
    )
    assert stats["missing_depths"] == 0, f"{stats['missing_depths']} missing depths"
    assert stats["ocean_cells"] > 0, "no ocean"


# --- open boundaries --------------------------------------------------------


def _bc(
    benchmark,
    row,
    tmp_path_factory,
    tmp_path,
    monkeypatch,
    source_res_deg,
    days,
    workers,
):
    from CrocoDash.forcing.mom6 import ConditionsConfigurator

    grid_dir = _grid(row, tmp_path_factory)
    ctx = _context(grid_dir, tmp_path)
    common = matrix.CASE["forcings"]["common"]
    start = datetime.fromisoformat(common["date_range"][0])
    conditions = ConditionsConfigurator(
        start_date=start.strftime("%Y%m%d"),
        end_date=(start + timedelta(days=days - 1)).strftime("%Y%m%d"),
        boundaries=BOUNDARIES,
        product_name=common["product_name"],
        function_name=common["function_name"],
        compset=BC_COMPSET,
        function_args={"resolution_deg": source_res_deg},  # reference_ocean's
    )
    _no_case(monkeypatch)
    conditions.configure()

    # First run, on every core: makes the raw data the timed run reuses.
    monkeypatch.delenv("CROCODASH_MAX_WORKERS", raising=False)
    _in_child(conditions.process_bc, ctx)
    for d in (ctx.regridded_data_dir, ctx.output_path):
        shutil.rmtree(d)  # with REGRID's cached weights
        d.mkdir()
    monkeypatch.setenv("CROCODASH_MAX_WORKERS", str(workers))
    peak_mb = _timed(benchmark, conditions.process_bc, ctx)

    # Source points: the horizontal size of each boundary's raw data.
    n_src = 0
    for b in BOUNDARIES:
        raw = sorted(ctx.raw_data_dir.glob(f"{b}_unprocessed*.nc"))[0]
        with xr.open_dataset(raw) as ds:
            n_src += ds.sizes["latitude"] * ds.sizes["longitude"]
    stats = _grid_stats(grid_dir)
    benchmark.extra_info.update(
        row=row,
        source_res_deg=source_res_deg,
        n_src=n_src,
        n_dst=2 * (stats["nx"] + stats["ny"]),  # boundary cells
        n_cells=stats["n_cells"],  # domain cells
        days=days,
        slices=math.ceil(days / REGRID_STEP_DAYS),
        workers=workers,
        peak_mb=peak_mb,
    )


@pytest.mark.parametrize("row", matrix.rows("bc"))
def test_bc(benchmark, row, tmp_path_factory, tmp_path, monkeypatch):
    _bc(
        benchmark,
        row,
        tmp_path_factory,
        tmp_path,
        monkeypatch,
        SOURCE_RES_DEG,
        DAYS,
        WORKERS,
    )


# --- runoff mapping ---------------------------------------------------------

_GLOFAS_CELLS = {}


def _runoff(benchmark, row, tmp_path_factory, tmp_path, monkeypatch, rmax):
    from mom6_forge.mapping import get_nn_map_filepath, get_smoothed_map_filepath

    from CrocoDash.forcing.runoff import RunoffConfigurator

    grid_dir = _grid(row, tmp_path_factory)
    rof_mesh = matrix.CASE["forcings"]["DROF"]["rof_esmf_mesh_filepath"]
    runoff = RunoffConfigurator(
        case_grid_name=row,
        case_session_id="checks",
        case_compset_lname=ROF_COMPSET,
        case_inputdir=str(tmp_path),
        case_esmf_mesh_path=str(grid_dir / "ocean_mesh.nc"),
        rmax=rmax,
        fold=rmax,
        rof_grid_name="GLOFAS",
        rof_esmf_mesh_filepath=rof_mesh,
    )
    _no_case(monkeypatch)
    runoff.configure()
    peak_mb = _timed(benchmark, runoff.process, _context(grid_dir, tmp_path))

    # The maps' weights (n_s) are what CESM's coupler pays for, a route handle
    # per map: record them from the files, then delete the files (GBs each).
    mapping_dir = tmp_path / "mapping"
    prefix = f"GLOFAS_to_{row}_map"
    maps = {
        "nn": get_nn_map_filepath(prefix, mapping_dir),
        "nnsm": get_smoothed_map_filepath(prefix, mapping_dir, rmax, rmax),
    }
    for key, path in maps.items():
        with xr.open_dataset(path) as ds:
            benchmark.extra_info[f"{key}_n_s"] = int(ds.sizes["n_s"])
        benchmark.extra_info[f"{key}_file_mb"] = path.stat().st_size / 1024**2
    shutil.rmtree(mapping_dir)

    if rof_mesh not in _GLOFAS_CELLS:  # the header only: the mesh is 1.3 GB
        with xr.open_dataset(rof_mesh) as ds:
            _GLOFAS_CELLS[rof_mesh] = int(ds.sizes["elementCount"])
    stats = _grid_stats(grid_dir)
    benchmark.extra_info.update(
        row=row,
        rmax_km=rmax,
        fold_km=rmax,
        n_src=_GLOFAS_CELLS[rof_mesh],
        n_cells=stats["n_cells"],
        n_ocn=stats["ocean_cells"],
        ocn_cell_km2=stats["ocean_cell_km2"],
        peak_mb=peak_mb,
    )


@pytest.mark.parametrize("row", matrix.rows("runoff"))
def test_runoff(benchmark, row, tmp_path_factory, tmp_path, monkeypatch):
    _runoff(benchmark, row, tmp_path_factory, tmp_path, monkeypatch, RMAX_KM)


# --- the sweeps -------------------------------------------------------------


@pytest.mark.parametrize("row, source_res_deg, days, workers", _bc_sweep())
def test_bc_sweep(
    benchmark,
    row,
    source_res_deg,
    days,
    workers,
    tmp_path_factory,
    tmp_path,
    monkeypatch,
):
    _bc(
        benchmark,
        row,
        tmp_path_factory,
        tmp_path,
        monkeypatch,
        source_res_deg,
        days,
        workers,
    )


@pytest.mark.parametrize("row, rmax", _runoff_sweep())
def test_runoff_sweep(benchmark, row, rmax, tmp_path_factory, tmp_path, monkeypatch):
    _runoff(benchmark, row, tmp_path_factory, tmp_path, monkeypatch, rmax)
