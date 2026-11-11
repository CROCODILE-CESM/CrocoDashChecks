# Integration

CrocoDash's workflow, checked end to end on every grid of the test matrix, two ways.

| File | What it is |
|---|---|
| `matrix.yaml` | The test matrix: one row per grid, with the forcings to run on it and whether the CESM runs use it |
| `case.yaml` | The CrocoDash case config every check starts from, without its grid; a row can change it |
| `matrix.py` | Reads both: the rows, and each row's full case config |
| `test_workflow.py`, `workflow.pbs` | **The workflow**, run by hand on Casper: builds every grid once with its bathymetry, runs the forcings turned on for it, and times every step. Results: `workflow.json` (timings) and `workflow.xml` (what passed, failed or was skipped, and why) |
| `run_mom_tests.py`, `run_mom_tests.pbs`, `cron_submit.sh` | **The weekly CESM runs**, Mondays on Derecho: MOM_interface's regional tests built with CrocoDash on the matrix's grids and run in CESM. Results: `cesm_runs.json` on the `test-results` branch |
| `mom6_scaling.json` | A hand-run sweep of MOM6's speed against its task count |

How the matrix and the workflow work, and how to run the workflow:
[How it works](https://crocodile-cesm.github.io/CrocoDashChecks/how_it_works.html). The rest of
this page is about the weekly CESM runs.

## The weekly CESM runs

They check that the current CrocoDash sets up the regional coupled compsets so that they actually run.

**What gets tested is not defined here.** It comes from MOM_interface's `testlist_mom.xml` in the CESM checkout. `run_mom_tests.py` selects every regional (`grid="USER_RES"`) `SMS` test for the machine and compiler. It keeps only the test's compset and options (`_D`, `_Ld2`, `_P<n>`) and rebuilds the case with CrocoDash on each grid the test matrix (`matrix.yaml`) marks `cesm_runs: true`, from the case config every check shares (`case.yaml`), instead of the test's Panama testmods. It then runs the case and records each phase in a CIME `TestStatus` file.

- **Restart and other multi-run tests** (ERS etc.) are skipped. CESM's own `create_test` runs those with the Panama testmods, and they don't depend on CrocoDash output.
- **To cover a new compset,** add the test to `testlist_mom.xml` in MOM_interface. It is picked up here automatically.

### Run

Needs a checkout of `CROCODILE-CESM/CESM` branch `crocodash`, and a conda env with CrocoDash's dependencies (`CrocoDash`). The job clones CrocoDash itself: a fresh clone of `main` every run, or of `CROCODASH_BRANCH` if you set it.

```bash
git clone -b crocodash https://github.com/CROCODILE-CESM/CESM ~/CESM_crocodash
(cd ~/CESM_crocodash && ./bin/git-fleximod update)

cd integration
qsub -v CESMROOT=$HOME/CESM_crocodash run_mom_tests.pbs
qsub -v CESMROOT=$HOME/CESM_crocodash,CROCODASH_BRANCH=my-branch run_mom_tests.pbs   # another branch
# from Casper: qsub -q main@desched1 ...
```

`python run_mom_tests.py --cesmroot ~/CESM_crocodash --test-root /tmp/x --dry-run` lists the tests that would run.

### Weekly runs and the dashboard

`cron_submit.sh` runs from your crontab on NCAR's cron server. It submits `run_mom_tests.pbs` with:
- `UPDATE=1`: reset this repo and the CESM clone to their branch tips first (the cron server has no git, so the job does this). CrocoDash is always a fresh clone of `main`;
- `PUBLISH=1`: push `cesm_runs.json` (the commits tested and every test's phases) to this repo's `test-results` branch, which the [dashboard](https://crocodile-cesm.github.io/CrocoDashChecks/) and its badge read when the site next rebuilds (at the latest, after the next daily data-access push).

PBS mails you when the job ends; its log is in `$CI_ROOT/logs/`. The push uses the token from your `gh` login (`gh auth login` once on GLADE, e.g. on Casper).

One-time setup:

```bash
CI_ROOT=/glade/work/$USER/croc_ci
git clone https://github.com/CROCODILE-CESM/CrocoDashChecks $CI_ROOT/CrocoDashChecks
git clone -b crocodash https://github.com/CROCODILE-CESM/CESM $CI_ROOT/CESM
(cd $CI_ROOT/CESM && ./bin/git-fleximod update)

ssh cron.hpc.ucar.edu
crontab -e
# Mondays 02:00:
0 2 * * 1 /glade/work/$USER/croc_ci/CrocoDashChecks/integration/cron_submit.sh >> /glade/work/$USER/croc_ci/cron.log 2>&1
```

The `CrocoDash` conda env supplies the dependencies; the job's CrocoDash clone goes first on `PYTHONPATH` and is deleted when the job ends. Update the env when CrocoDash's `environment.yml` gains a dependency.

### Results

Each test gets its own directory under `$TESTROOT`:

```
SMS_D_Ld2.USER_RES.CR1850MARBL_JRA_GLOFAS.derecho_intel.crocodash-<grid>.<testid>/
  TestStatus              CIME format: CREATE_NEWCASE, XML, SETUP, ..., RUN
  croc_test.log           output of every command
  crocodash_config.yaml   the exact config passed to `crocodash create`
  <same name as the test dir>/   the case (unique name, so each test gets its own CIME build/run dir)
inputdir/<compset>.<grid>.<testid>/     the case's forcing (kept short: MOM6 truncates INPUTDIR at 128 characters)
```

Check the results with CIME's own tool:

```bash
$TESTROOT/cs.status.<testid>
```

| Phase | What it covers |
|---|---|
| `CREATE_NEWCASE` | `crocodash create`, including configuring and processing forcings |
| `XML` | applying the test options, plus `NTASKS=--ntasks` (4) on every component and `--data-ntasks` (56 in the PBS job) on DATM, DROF and the mediator, launched with `mpiexec -n` so parallel tests don't share cores |
| `SETUP` | `case.setup --reset` (crocodash create already ran case.setup) |
| `SHAREDLIB_BUILD` / `MODEL_BUILD` | `case.build` |
| `SUBMIT` / `RUN` | `case.submit --no-batch`; RUN passes only if `CaseStatus` records `case.run success` |

### Grids, bathymetry and forcing

- **Grids:** every compset runs on each `matrix.yaml` row with `cesm_runs: true` (now `labrador`, a coast with sea ice and rivers, and `equator_180e`, across the antimeridian), with any changes that row makes to `case.yaml`. A polar grid is written as a supergrid file first, since CrocoDash's config only builds latitude/longitude boxes itself. `--grids` overrides the list for a hand run, e.g. `EXTRA="--grids north_pole"` on the `qsub`.
- **Bathymetry** (`case.yaml`): GEBCO coarsened 8× (1/30°), with 10 uniform levels. It is plenty for these grids, and a polar cap fits in memory, which full GEBCO doesn't.
- **Ocean, ice and wave forcing:** the synthetic `reference_*` products, so nothing is downloaded.
- **Runoff, river nutrients and the MARBL IC:** real files on GLADE; runoff is mapped from the GLOFAS mesh CESM's own DROF reads.
- **How forcing args are selected:** they are grouped by compset component, and each test gets only the groups its compset uses.
