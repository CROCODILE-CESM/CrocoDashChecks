# MOM6 NTASKS_OCN Scaling Test — Setup Notes

How the `results/mom6_scaling.json` / `report/mom6_scaling.html` numbers were produced.
This is a hand-run CESM case sweep, not a pytest-benchmark suite — see
`how_benchmarking_works.md` for that side of CrocoDashChecks. Scripts and notebooks referenced
below live under `dev/scaling_test/` in the outer croc monorepo, not in this repo.

---

## Case setup

- **Grid**: `Grid(lenx=10.0, leny=10.0, resolution=0.1)` → 100×100 points, flat bathymetry
  at 1000 m, `VGrid.uniform(nk=10)`.
- **Compset**: `1850_DATM%NYF_SLND_SICE_MOM6%REGIONAL_SROF_SGLC_SWAV`, `machine="derecho"`.
- **Forcings**: GLORYS, `date_range=["2020-01-01", "2020-01-31"]` (30 simulated days).
- **Queue**: `develop` (`cpudev`) on Derecho — shared-node, fast turnaround, `walltimemax`
  is 1 hour and `jobmax` is 63 total PEs, both of which matter below.
- **Sweep**: `NTASKS_OCN` = 1, 2, 4, 5, 10, 20 — one CESM case per value
  (`~/croc_cases/scaling_n{N}`), all reading forcing/grid data from one master case dir.

## Two problems with the "one shared inputdir" approach, and the fix

The obvious design — build the grid + forcings once, then create 6 CESM cases that all
point at that one `inputdir` with different `caseroot`s and `ntasks_ocn` — doesn't work
against CrocoDash's `Case` class as-is:

1. **`Case.__init__` requires `override=True` whenever `inputdir` already exists**, and
   `override=True` unconditionally `shutil.rmtree`s the whole `inputdir` before recreating
   it — so reusing a shared, already-processed `inputdir` for a second case destroys it.
2. **`ocn_grid.name` gets registered globally** in CIME's `component_grids_nuopc.xml`
   (shared across the whole `cesmroot` install, not scoped to one case). A second case
   using the same grid name hits the same override requirement, and setting
   `override=True` there would silently repoint the *first* case's registry entry at the
   second case's mesh file.

**Fix** (see `dev/scaling_test/create_ntasks_case_workaround.py`): give every
`scaling_n{N}` case its own fresh `inputdir` and its own uniquely-named grid
(`scaling_test_n{N}` — safe to rename, since `mom6_forge.git_utils.get_domain_dir` hashes
on grid coordinate values, not name), then repoint `user_nl_mom`'s `INPUTDIR` at the
*master* case's `ocnice/` folder instead of copying forcing files into each case. This
works because `Case.configure_forcings()`/`_update_forcing_variables()` writes only
bare/relative filenames into `user_nl_mom` (`TEMP_SALT_Z_INIT_FILE = init_tracers.nc`,
`OBC_SEGMENT_001_DATA = "...file:forcing_obc_segment_001.nc..."`, etc.) — never an
absolute path — so every case's `user_nl_mom` already references the exact filenames
sitting in the master's `ocnice/`. Only `INPUTDIR`, `GRID_FILE`, `TOPO_FILE`, and
`ALE_COORDINATE_CONFIG` need rewriting after `configure_forcings()` runs, since those are
the only parameters carrying this case's own (differently-suffixed) grid filenames instead
of the master's.

Net effect: the expensive step (`process_forcings` — GLORYS download + regrid) runs
**once**, on the master case only; every `scaling_n{N}` case creation is cheap (just CIME
case creation + a few file edits).

## PE layout: shrinking the whole case, not just the ocean

Setting `ntasks_ocn=N` via `Case()` (or `xmlchange NTASKS_OCN=N`) only resizes the ocean
component. Every other component (`DATM`, stub `LND`/`ICE`/`ROF`/`GLC`/`WAV`, `CPL`) stays
at CESM's default PE count (128 in this compset), so the case's *real* total PE footprint
stays ~128+N — comfortably over the `develop` queue's `jobmax=63`, causing
`case.setup`/`case.submit` to fail with "No queues found" even though `NTASKS_OCN` looks
correct. Since every non-ocean component here is a cheap stub or data-only component, the
fix is to collapse everything onto the same N tasks, fully overlapping:

```bash
./xmlchange NTASKS=<N>    # sets NTASKS for every component at once
./xmlchange ROOTPE=0      # every component starts at PE 0 — fully concurrent layout
./case.setup --reset
```

## Wallclock

`JOB_WALLCLOCK_TIME` defaults to CESM's standard 12 hours for `case.run`, which exceeds
`develop`'s 1-hour cap outright. Set it explicitly and low, since these are short runs:

```bash
./xmlchange JOB_WALLCLOCK_TIME=00:30:00 --subgroup case.run
```

Watch the smallest-`N` case in particular — it's the slowest and has the least margin. You
can check live progress against the wallclock by tailing the run directory's MOM6
diagnostics before the job finishes (its cadence roughly says how much of the requested
simulated period is done):

```bash
tail -f /glade/derecho/scratch/$USER/scaling_n1/run/ocean.stats
```

## PATH pollution gotcha

If a `conda`-managed Python environment's `bin/` directory ends up prepended to `PATH` in
the shell running CIME scripts (e.g. from an unrelated `conda run -n <env> ...` call, or an
IDE's integrated terminal defaulting to that environment), `case.build` can fail deep
inside MOM6's `cime_config/buildnml` with:

```
ModuleNotFoundError: No module named 'tools.utils'
```

This happens because Python resolves the generic top-level module name `tools` against
*whatever* `tools` package is importable first on `sys.path` — including an unrelated
`tools/` package from a different project entirely — instead of MOM6's own
`components/mom/cime_config/tools/utils.py`. Fix: strip the offending directory from `PATH`
before running `case.build`/`case.submit`/`qcmd`:

```bash
export PATH=$(echo "$PATH" | tr ':' '\n' | grep -v '^/path/to/offending/env/bin$' | paste -sd: -)
```

## Collecting results

Each finished case writes `case_dir/timing/cesm_timing.$CASE.$jobid` (CIME's native
Model Cost / Model Throughput / per-component timing summary). The `ocean-debugger` MCP
server's `read_cesm_timing(case_dir)` tool parses this file directly — see
`dev/MCP_regional_ocean_debugger/tools/timing.py` in the outer croc monorepo. Sanity-check
each run before trusting its number (`find_errors`/manually grepping the archived
`ocn.log.*.gz` for `FATAL`/`NaN`/large CFL) — `st_archive` moves logs out of `case_dir` into
`$SCRATCH/archive/<case>/logs/*.gz`, which the current `find_errors` tool doesn't look
inside (a known gap, not yet fixed).

## Schema

`results/mom6_scaling.json`:

```json
{
  "grid": "...", "compset": "...", "machine": "...", "queue": "...", "date_range": [...],
  "points": [
    {"ntasks_ocn": N, "throughput_sim_years_per_day": ..., "tot_run_time_s": ..., "ocn_cost_pe_hrs": ...},
    ...
  ]
}
```

`scripts/generate_scaling_report.py` reads this and renders `report/mom6_scaling.html` —
one line chart (throughput vs. `NTASKS_OCN`, reusing `generate_report.py`'s
`_linechart_svg`) plus a table with parallel efficiency computed relative to the smallest
`NTASKS_OCN` point present in the data.
