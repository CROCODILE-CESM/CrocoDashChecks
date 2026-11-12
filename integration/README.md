# Integration

| File | What it is |
|---|---|
| `matrix.yaml` | The matrix: one row per grid, with its forcings and `cesm_runs`, in two parts: `testing` (weekly) and `performance` (monthly) |
| `case.yaml` | The CrocoDash case config every row starts from; a row can change it |
| `matrix.py` | Reads both |
| `test_workflow.py` | A row's case through the CrocoDash CLI, timed, and its CESM runs |
| `workflow.pbs` | One row on one Derecho node (`ROW=`) |
| `collect.pbs` | Merges a suite's rows into `testing.*` or `performance.*` and publishes them |
| `mom6_scaling.json` | A hand-run sweep of MOM6's speed against its task count |

Schedule, and running by hand: [How it works](https://crocodile-cesm.github.io/CrocoDashChecks/how_it_works.html).

## The steps, for each row

| Step | What it runs |
|---|---|
| `test_create` | `crocodash create --configure-only` in `CR_JRA_GLOFAS`, timed and profiled into grid, bathymetry, vertical grid and CESM case |
| `test_bc`, `test_runoff` | `crocodash process --bc` / `--runoff` on that case, for each forcing the row lists |
| `test_bc_sweep`, `test_runoff_sweep` | the same from an edited copy of the case's forcing config, on a few performance rows, for the Performance fits |
| `test_cesm` | on `cesm_runs` rows: every regional (`USER_RES`) `SMS` test in MOM_interface's `testlist_mom.xml` as a case on the row, built and run |

## The CESM runs

- **Which:** MOM_interface's test list decides; to cover a new compset, add a test there. Each
  keeps its compset and options (`_D`, `_Ld2`, `_P<n>`), but not its Panama testmods.
- **The cases:** `CR_JRA_GLOFAS` is the row's own case; every other compset is a new case made
  from the row case's grid, bathymetry and vertical grid files. Each gets only the `case.yaml`
  forcing blocks its compset uses.
- **Skipped:** restart and other multi-run tests (ERS etc.); CESM's own `create_test` covers them.
- **Cost:** about 20 minutes each, nearly all of it CESM starting up (DATM reading JRA's time
  bounds, DROF mapping GLOFAS); the 2-day run itself is under a minute.

| Phase | What it covers |
|---|---|
| `CREATE_NEWCASE` | `crocodash create` and `crocodash process --all` |
| `XML` | the test options, plus 4 tasks per component and 56 for DATM, DROF and the mediator |
| `SETUP` | `case.setup --reset` |
| `SHAREDLIB_BUILD` / `MODEL_BUILD` | `case.build` |
| `SUBMIT` / `RUN` | `case.submit --no-batch`; RUN passes only if `CaseStatus` records `case.run success` |

Every case is in `/glade/derecho/scratch/$USER/croc_tests/<grid>.<compset>.<run>/`, its forcing
in `inputdir/` beside it (kept short: MOM6 truncates `INPUTDIR` at 128 characters), and a CESM
run's command output in `<grid>.<compset>.<run>.log`.
