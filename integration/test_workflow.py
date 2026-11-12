"""CrocoDash on every grid in matrix.yaml, through its own CLI on real cases,
timed: an integration test and a benchmark in one, run weekly on one Derecho
node by workflow.pbs.

For each row of matrix.yaml:
  1. test_create makes the row's case with `crocodash create --configure-only`,
     in BASE_COMPSET, from case.yaml plus the row: grid, bathymetry, vertical
     grid, the CESM case, and its forcings configured. It runs under Python's
     profiler, which splits its time into those parts.
  2. test_bc and test_runoff run `crocodash process --bc` or `--runoff` on that
     case, for each forcing the row turns on.
  3. On rows with cesm_runs, test_cesm runs every regional SMS test in
     MOM_interface's testlist_mom.xml as a case on the row: the row's own case
     for BASE_COMPSET, and for every other compset a new case made from the row
     case's grid, bathymetry and vertical grid files. Each processes all its
     forcings, takes the test's options, builds and runs; the phases go to
     cesm_runs.json.
A step on a row whose case failed to create is skipped.

The sweeps vary what isn't a grid, on a few rows, for the Performance page's
fits: `crocodash process --config` on an edited copy of the row case's forcing
config, so they overwrite that case's forcing files (sweep rows don't run CESM).

Every step runs in a forked child, timed once, with the peak memory of its whole
process tree. The cases are kept.

Environment:
  CESMROOT        a checkout of CESM's crocodash branch (required)
  CASES_ROOT      where the cases go (default /glade/derecho/scratch/$USER/croc_tests);
                  keep it short: MOM6 truncates INPUTDIR at 128 characters
  RUN_ID          names this run's cases (default: the time now)
  CESM_RUNS_JSON  where the CESM tests' summary goes (default integration/cesm_runs.json)

From the repo root, in the CrocoDash env, after `source crocodash_main.sh`:
    CESMROOT=... pytest integration/test_workflow.py \\
        --benchmark-json=integration/workflow.json --junitxml=integration/workflow.xml
"""

import cProfile
import functools
import json
import math
import os
import pstats
import shutil
import subprocess
import sys
import threading
import traceback
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import psutil
import pytest
import xarray as xr
import yaml

import matrix

CESMROOT = Path(os.environ["CESMROOT"]) if os.environ.get("CESMROOT") else None
CASES_ROOT = Path(
    os.environ.get(
        "CASES_ROOT", f"/glade/derecho/scratch/{os.environ.get('USER')}/croc_tests"
    )
)
RUN_ID = os.environ.get("RUN_ID", datetime.now().strftime("%Y%m%d_%H%M"))
CESM_RUNS_JSON = Path(os.environ.get("CESM_RUNS_JSON", matrix.ROOT / "cesm_runs.json"))
MACHINE, COMPILER, PROJECT = "derecho", "intel", "NCGD0011"

# Every row's own case: a GLOFAS compset, so runoff can run on any row, and one
# of the testlist's, so a CESM row's own case is one of its tests.
BASE_COMPSET = "CR_JRA_GLOFAS"
BOUNDARIES = ["south", "north", "west", "east"]
REGRID_STEP_DAYS = 30  # ConditionsConfigurator's slice

# The row cases' settings, from case.yaml; open boundaries on one worker.
_COMMON = matrix.CASE["forcings"]["common"]
START = datetime.fromisoformat(_COMMON["date_range"][0])
DAYS = (datetime.fromisoformat(_COMMON["date_range"][1]) - START).days + 1
SOURCE_RES_DEG = _COMMON["function_overrides"]["resolution_deg"]
RMAX_KM = matrix.CASE["forcings"]["DROF"]["rmax"]
WORKERS = 1

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
# indo_pacific at rmax 80 has ~1.6e9 weights (73% of 2^31) and peaks near 76 GB;
# rmax 100 would pass 2^31, so the sweep stops at 80.
RUNOFF_SWEEP_ROWS = ["gulf_of_mexico", "north_atlantic", "indo_pacific"]
RUNOFF_RMAX_KM = [10, 20, 40, 80]

# What `crocodash create` spends its time on: {part: (file, function)}.
PROFILED = {
    "grid_s": ("CrocoDash/recipe.py", "build_grid"),
    "topo_s": ("CrocoDash/recipe.py", "build_topo"),
    "vgrid_s": ("CrocoDash/recipe.py", "build_vgrid"),
    "case_s": ("CrocoDash/case.py", "__init__"),
    "configure_s": ("CrocoDash/case.py", "configure_forcings"),
}

STOP_OPTIONS = {"Ln": "nsteps", "Lh": "nhours", "Ld": "ndays", "Lm": "nmonths"}
NTASKS, DATA_NTASKS = 4, 56  # CESM tests: per component; DATM, DROF and the mediator


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


def _cesm_tests():
    """(row, test, compset, test options, testlist options) for every regional
    SMS test in MOM_interface's testlist, on every row with cesm_runs."""
    if CESMROOT is None:
        return []
    sys.path.insert(0, str(CESMROOT / "cime"))
    from CIME.utils import parse_test_name
    from CIME.XML.testlist import Testlist

    testlist = CESMROOT / "components/mom/cime_config/testdefs/testlist_mom.xml"
    tests, seen = [], set()
    for t in Testlist(str(testlist)).get_tests(machine=MACHINE, compiler=COMPILER):
        test, opts, grid, compset, *_ = parse_test_name(
            f"{t['testname']}.{t['grid']}.{t['compset']}"
        )
        if grid != "USER_RES" or test != "SMS" or (t["testname"], compset) in seen:
            continue
        seen.add((t["testname"], compset))
        for row in matrix.rows("cesm_runs"):
            tests.append(
                pytest.param(
                    row,
                    t["testname"],
                    compset,
                    opts or [],
                    t.get("options", {}),
                    id=f"{row}-{compset}",
                )
            )
    return tests


def _longname(compset):
    for f in (CESMROOT / "components").glob("*/cime_config/config_compsets.xml"):
        for node in ET.parse(f).getroot().iter("compset"):
            if node.findtext("alias") == compset:
                return node.findtext("lname")
    return compset  # already a longname


def _git_ref(path):
    """{"branch", "commit"} of a checkout, or None outside one."""

    def git(*a):
        r = subprocess.run(["git", "-C", str(path), *a], capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else None

    commit = git("rev-parse", "--short", "HEAD") if path else None
    return (
        {"branch": git("rev-parse", "--abbrev-ref", "HEAD"), "commit": commit}
        if commit
        else None
    )


@pytest.fixture(scope="session", autouse=True)
def _import_crocodash_once():
    """Import CrocoDash here, once, so every step's forked child inherits it
    rather than timing its own import (the first, from a cold disk, took 40 s)."""
    import CrocoDash.cli  # noqa: F401
    import CrocoDash.recipe  # noqa: F401


@pytest.fixture(scope="session", autouse=True)
def _crocodash_tested(record_testsuite_property):
    """Record in workflow.xml which CrocoDash this run tested: the clone
    crocodash_main.sh made."""
    ref = _git_ref(os.environ.get("CROCODASH_SRC"))
    if ref:
        for name, value in ref.items():
            record_testsuite_property(f"crocodash_{name}", value)


_CESM = []  # cesm_runs.json's tests, as test_cesm runs them


@pytest.fixture(scope="session", autouse=True)
def _cesm_summary():
    """After the run, write cesm_runs.json if any CESM test ran."""
    yield
    if _CESM:
        summary = {
            "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "cesm": _git_ref(CESMROOT),
            "crocodash": _git_ref(os.environ.get("CROCODASH_SRC")),
            "tests": _CESM,
        }
        CESM_RUNS_JSON.write_text(json.dumps(summary, indent=1) + "\n")


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


def _crocodash(*argv, profile=None):
    """Run the crocodash CLI with these arguments, as the `crocodash` command
    does. With profile, run it under Python's profiler and write the seconds
    spent in each PROFILED part to that file."""
    from CrocoDash.cli import main

    sys.argv = ["crocodash", *map(str, argv)]
    if profile is None:
        return main()
    profiler = cProfile.Profile()
    profiler.runcall(main)
    seconds = dict.fromkeys(PROFILED, 0.0)
    for (path, _, func), (*_, cumtime, _) in pstats.Stats(profiler).stats.items():
        for part, (suffix, name) in PROFILED.items():
            if path.endswith(suffix) and func == name:
                seconds[part] += cumtime
    Path(profile).write_text(json.dumps(seconds))


# --- the cases --------------------------------------------------------------


def _paths(row, compset):
    """A case's caseroot and inputdir. Its name is unique per run, since it also
    names CIME's build and run directories."""
    name = f"{row}.{compset}.{RUN_ID}"
    return CASES_ROOT / name, CASES_ROOT / "inputdir" / name


def _config(row, compset, workdir, files=None):
    """The config `crocodash create` reads: case.yaml plus the row, this case's
    compset and paths, and only the forcing blocks the compset uses. files: a
    case's state, whose grid, bathymetry and vertical grid files to reuse."""
    caseroot, inputdir = _paths(row, compset)
    cfg = matrix.config(row, workdir)
    if files:
        cfg["grid"] = {"supergrid_path": files["supergrid_path"], "name": row}
        cfg["topo"] = {
            "min_depth": cfg["topo"]["min_depth"],
            "source": {"type": "from_file", "topo_file_path": files["topo_path"]},
        }
        cfg["vgrid"] = {"type": "from_file", "filename": files["vgrid_path"]}
    cfg["case"] = {
        **cfg.get("case", {}),
        "cesmroot": str(CESMROOT),
        "caseroot": str(caseroot),
        "inputdir": str(inputdir),
        "compset": compset,
        "machine": MACHINE,
        "project": PROJECT,
    }
    lname, forcings = _longname(compset), {}
    for key, kwargs in cfg["forcings"].items():
        if key == "common" or all(part in lname for part in key.split("+")):
            forcings.update(kwargs)
    cfg["forcings"] = forcings
    path = workdir / "crocodash_config.yaml"
    path.write_text(yaml.safe_dump(cfg))
    return path


def _create(config, workdir, *flags, profile=None):
    os.chdir(workdir)  # anything create leaves behind stays out of the repo
    CASES_ROOT.joinpath("inputdir").mkdir(parents=True, exist_ok=True)
    _crocodash("create", "--config", config, *flags, profile=profile)


def _state(caseroot):
    """The case's own record of its files and inputdir."""
    from CrocoDash import case_state

    return case_state.read(caseroot)


_CASES = {}  # row -> its own case's caseroot, or why it failed to create
_STATS = {}  # row -> its grid's sizes


def _case(row, tmp_path_factory):
    """A row's own case, made once per run (untimed if test_create didn't run
    first); skips the calling test if it failed to create."""
    if row not in _CASES:
        workdir = tmp_path_factory.mktemp(row)
        config = _config(row, BASE_COMPSET, workdir)
        try:
            _in_child(_create, config, workdir, "--configure-only")
            _CASES[row] = _paths(row, BASE_COMPSET)[0]
        except RuntimeError as error:
            _CASES[row] = error
    if isinstance(_CASES[row], Exception):
        pytest.skip(f"its case failed to create: {_CASES[row]}")
    return _CASES[row]


def _grid_stats(row):
    """The row case's grid: its size, ocean cells and missing depths."""
    if row not in _STATS:
        from mom6_forge.grid import Grid

        state = _state(_CASES[row])
        with xr.open_dataset(state["topo_path"]) as ds:
            depth = ds["depth"].values
        ocean = depth > 0
        tarea = np.asarray(Grid.from_supergrid(state["supergrid_path"]).tarea) / 1e6
        _STATS[row] = {
            "nx": int(depth.shape[1]),
            "ny": int(depth.shape[0]),
            "n_cells": int(depth.size),
            "ocean_cells": int(ocean.sum()),
            "missing_depths": int(np.isnan(depth).sum()),
            "ocean_cell_km2": float(tarea[ocean].mean()) if ocean.any() else None,
        }
    return _STATS[row]


@pytest.mark.parametrize("row", matrix.rows())
def test_create(benchmark, row, tmp_path_factory):
    workdir = tmp_path_factory.mktemp(row)
    config = _config(row, BASE_COMPSET, workdir)
    profile = workdir / "profile.json"
    try:
        create = functools.partial(_create, profile=profile)
        peak_mb = _timed(benchmark, create, config, workdir, "--configure-only")
    except RuntimeError as error:
        _CASES[row] = error
        raise
    _CASES[row] = _paths(row, BASE_COMPSET)[0]
    stats = _grid_stats(row)
    spec = matrix.GRIDS[row]["grid"]
    source = yaml.safe_load(config.read_text())["topo"]["source"]
    benchmark.extra_info.update(
        row=row,
        area_deg2=None if matrix.is_polar(row) else spec["lenx"] * spec["leny"],
        bathymetry=os.path.basename(source.get("bathymetry_path", "")),
        peak_mb=peak_mb,
        **json.loads(profile.read_text()),
        **stats,
    )
    assert stats["missing_depths"] == 0, f"{stats['missing_depths']} missing depths"
    assert stats["ocean_cells"] > 0, "no ocean"


# --- open boundaries --------------------------------------------------------


def _process(caseroot, flag, config=None):
    """`crocodash process --<flag>` on the case, or from an edited copy of its
    forcing config."""
    where = ["--config", config] if config else ["--caseroot", caseroot]
    _crocodash("process", *where, f"--{flag}")


def _edited_config(caseroot, workdir, edit):
    """A copy of the case's forcing config, with edit(config) applied."""
    inputdir = Path(_state(caseroot)["inputdir"])
    cfg = json.loads((inputdir / "extract_forcings" / "config.json").read_text())
    edit(cfg)
    path = workdir / "config.json"
    path.write_text(json.dumps(cfg))
    return path


def _bc(benchmark, row, tmp_path_factory, tmp_path, monkeypatch, res, days, workers):
    caseroot = _case(row, tmp_path_factory)
    extract = Path(_state(caseroot)["inputdir"]) / "extract_forcings"
    config = None
    if (res, days) != (SOURCE_RES_DEG, DAYS):  # a sweep case

        def edit(cfg):
            inputs = cfg["conditions"]["inputs"]
            inputs["end_date"] = (START + timedelta(days=days - 1)).strftime("%Y%m%d")
            inputs["function_args"]["resolution_deg"] = res

        config = _edited_config(caseroot, tmp_path, edit)
    # Raw file names don't record the source resolution: start every case clean.
    for d in ("raw_data", "regridded_data"):
        shutil.rmtree(extract / d, ignore_errors=True)
        (extract / d).mkdir(parents=True)
    monkeypatch.setenv("CROCODASH_MAX_WORKERS", str(workers))
    peak_mb = _timed(benchmark, _process, caseroot, "bc", config)

    # Source points: the horizontal size of each boundary's raw data.
    n_src = 0
    for b in BOUNDARIES:
        raw = sorted((extract / "raw_data").glob(f"{b}_unprocessed*.nc"))[0]
        with xr.open_dataset(raw) as ds:
            n_src += ds.sizes["latitude"] * ds.sizes["longitude"]
    stats = _grid_stats(row)
    benchmark.extra_info.update(
        row=row,
        source_res_deg=res,
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


def _runoff(benchmark, row, tmp_path_factory, tmp_path, rmax):
    from mom6_forge.mapping import get_nn_map_filepath, get_smoothed_map_filepath

    caseroot = _case(row, tmp_path_factory)
    config = None
    if rmax != RMAX_KM:  # a sweep case; fold = rmax keeps the kernel's shape

        def edit(cfg):
            cfg["runoff"]["inputs"].update(rmax=rmax, fold=rmax)

        config = _edited_config(caseroot, tmp_path, edit)
    mapping = Path(_state(caseroot)["inputdir"]) / "mapping"
    prefix = f"GLOFAS_to_{row}_map"
    maps = {
        "nn": get_nn_map_filepath(prefix, mapping),
        "nnsm": get_smoothed_map_filepath(prefix, mapping, rmax, rmax),
    }
    for path in maps.values():  # every case makes both maps
        Path(path).unlink(missing_ok=True)
    peak_mb = _timed(benchmark, _process, caseroot, "runoff", config)

    # The maps' weights (n_s) are what CESM's coupler pays for, a route handle per map.
    for key, path in maps.items():
        with xr.open_dataset(path) as ds:
            benchmark.extra_info[f"{key}_n_s"] = int(ds.sizes["n_s"])
        benchmark.extra_info[f"{key}_file_mb"] = Path(path).stat().st_size / 1024**2
    if config:
        Path(maps["nnsm"]).unlink()  # a sweep's map is GBs and nothing reads it

    rof_mesh = matrix.CASE["forcings"]["DROF"]["rof_esmf_mesh_filepath"]
    if rof_mesh not in _GLOFAS_CELLS:  # the header only: the mesh is 1.3 GB
        with xr.open_dataset(rof_mesh) as ds:
            _GLOFAS_CELLS[rof_mesh] = int(ds.sizes["elementCount"])
    stats = _grid_stats(row)
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
def test_runoff(benchmark, row, tmp_path_factory, tmp_path):
    _runoff(benchmark, row, tmp_path_factory, tmp_path, RMAX_KM)


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
def test_runoff_sweep(benchmark, row, rmax, tmp_path_factory, tmp_path):
    _runoff(benchmark, row, tmp_path_factory, tmp_path, rmax)


# --- the CESM runs ----------------------------------------------------------


def _xmlchanges(opts, options):
    """The xmlchanges for a test's options (_D, _Ld2, _P<n>) and its layout."""
    changes, ntasks = [], NTASKS
    for opt in opts:
        if opt == "D":
            changes.append("DEBUG=TRUE")
        elif opt[:2] in STOP_OPTIONS:
            changes.append(f"STOP_OPTION={STOP_OPTIONS[opt[:2]]},STOP_N={opt[2:]}")
        elif opt.startswith("P") and opt[1:].isdigit():
            ntasks = int(opt[1:])
        else:
            raise ValueError(f"unsupported test option _{opt}")
    # The small ocean, ice and wave grids decompose onto a few tasks, but DATM
    # and DROF read global data, so they and the mediator get more.
    data = max(DATA_NTASKS, ntasks)
    changes += [
        f"NTASKS={ntasks},ROOTPE=0",
        f"NTASKS_ATM={data},NTASKS_ROF={data},NTASKS_CPL={data}",
        # Derecho's default launcher takes every core in the job: launch exactly these.
        f"MPI_RUN_COMMAND=mpiexec -n {data} --cpu-bind none",
    ]
    if "wallclock" in options:
        changes.append(f"JOB_WALLCLOCK_TIME={options['wallclock']}")
    return changes


def _run(cmd, log, cwd):
    with open(log, "a") as f:
        f.write(f"\n$ {' '.join(cmd)}\n")
        f.flush()
        return (
            subprocess.run(cmd, cwd=cwd, stdout=f, stderr=subprocess.STDOUT).returncode
            == 0
        )


@pytest.mark.parametrize("row, test, compset, opts, options", _cesm_tests())
def test_cesm(row, test, compset, opts, options, tmp_path_factory, tmp_path):
    phases = []
    _CESM.append(
        {
            "name": f"{test}.USER_RES.{compset}.{MACHINE}_{COMPILER}.crocodash-{row}",
            "test": test,
            "compset": compset,
            "grid": row,
            "longname": _longname(compset),
            "phases": phases,
            "passed": False,
        }
    )
    caseroot = _paths(row, compset)[0]
    log = CASES_ROOT / f"{caseroot.name}.log"

    def phase(name, ok, why=""):
        phases.append([name, "PASS" if ok else "FAIL"])
        if not ok:
            pytest.fail(f"{name} failed: {why or f'see {log}'}")

    try:
        base = _case(row, tmp_path_factory)
    except pytest.skip.Exception:
        phases.append(["CREATE_NEWCASE", "FAIL"])
        raise
    try:
        if compset == BASE_COMPSET:
            _in_child(_crocodash, "process", "--caseroot", base, "--all")
        else:  # a new case on the row case's grid, bathymetry and vertical grid
            config = _config(row, compset, tmp_path, files=_state(base))
            _in_child(_create, config, tmp_path)
        phase("CREATE_NEWCASE", True)
    except RuntimeError as error:
        phase("CREATE_NEWCASE", False, str(error))
    try:
        changes = _xmlchanges(opts, options)
    except ValueError as error:
        phase("XML", False, str(error))
    phase("XML", all(_run(["./xmlchange", c], log, caseroot) for c in changes))
    # crocodash create already ran case.setup: redo it for the new layout.
    phase("SETUP", _run(["./case.setup", "--reset"], log, caseroot))
    built = _run(["./case.build"], log, caseroot)
    phase("SHAREDLIB_BUILD", built)
    phase("MODEL_BUILD", built)
    phase("SUBMIT", _run(["./case.submit", "--no-batch"], log, caseroot))
    # case.run logs "success" only after CIME checks the coupler log's last line.
    status = caseroot / "CaseStatus"
    ran = status.exists() and "case.run success" in status.read_text()
    phase("RUN", ran, f"see {status}")
    _CESM[-1]["passed"] = True
