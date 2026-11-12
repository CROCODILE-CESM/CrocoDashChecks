# How it works

Every Monday at 02:00 MT, three checks run against a fresh clone of CrocoDash `main`:

| Check | What it does | Where | Results |
|---|---|---|---|
| Workflow | Builds every grid in the test matrix, runs its forcings, times each step | Casper | `integration/workflow.json`, `workflow.xml` on `main` |
| CESM runs | Builds MOM_interface's regional SMS tests with CrocoDash on the grids marked `cesm_runs`, and runs them | Derecho | `cesm_runs.json` on `test-results` |
| Data access | Calls every way CrocoDash fetches data | Casper | `data_access/health.json` on `main` |

## The test matrix

- [`integration/matrix.yaml`](https://github.com/CROCODILE-CESM/CrocoDashChecks/blob/main/integration/matrix.yaml):
  one row per grid, with the forcings to run on it (`bc`, `runoff`) and `cesm_runs: true`.
- [`integration/case.yaml`](https://github.com/CROCODILE-CESM/CrocoDashChecks/blob/main/integration/case.yaml):
  the CrocoDash case config every row starts from (coarse GEBCO, synthetic forcing); a row can
  change it under `case:`.
- To add a grid, add a row; to turn a step off, delete it from its row.
- A row with `cesm_runs: true` lists every forcing too, since the CESM runs build them all
  (`matrix.py` refuses a matrix that doesn't).

## The weekly run

- One crontab line on `cron.hpc.ucar.edu` (`crontab -e` there) submits a small Casper job that
  clones this repo and runs `weekly.sh`:

  ```
  0 2 * * 1 /opt/pbs/bin/qsub -q casper@casper-pbs -A NCGD0011 -l select=1:ncpus=1:mem=4GB -l walltime=00:30:00 -j oe -o /glade/derecho/scratch/$USER/crocodashchecks/ -- /bin/bash -c 'D=$(mktemp -d) && git clone -q https://github.com/CROCODILE-CESM/CrocoDashChecks $D && bash $D/weekly.sh' >> /glade/derecho/scratch/$USER/crocodashchecks/cron.log 2>&1
  ```
- `weekly.sh` copies the clone to `/glade/derecho/scratch/$USER/crocodashchecks/<date>/` and
  submits the three jobs from there; their logs go to its `logs/`. Runs older than four weeks are
  deleted.
- Each job clones CrocoDash `main` (the CESM job also CESM's `crocodash` branch), runs, and pushes
  its results with your `gh` login's token. Each push rebuilds this site.
- CESM test directories: `/glade/derecho/scratch/$USER/croc_tests/`.

## Running a check by hand

From a clone of this repo, in the `CrocoDash` conda env:

```bash
# the workflow (-v PYTEST_ARGS="-k pole" runs only the steps matching "pole")
qsub -q casper@casper-pbs integration/workflow.pbs
# data access
qsub -q casper@casper-pbs data_access/check.pbs
# the CESM runs
cd integration
qsub -q main@desched1 -v CESMROOT=$SCRATCH/CESM run_mom_tests.pbs
```

- `CESMROOT` is cloned there first if it doesn't exist.
- `-v CROCODASH_BRANCH=my-branch` tests another CrocoDash branch; `-v PUBLISH=1` publishes the
  results (full runs only).
- To run Python directly, `source crocodash_main.sh` first, or the env's own older CrocoDash is
  tested.

## This site

- `.github/workflows/publish.yml` rebuilds it on every push to `main` or `test-results`.
- The Status and Performance pages are notebooks (`site/*.ipynb`) that read the results files;
  edit them in Jupyter. Shared code is in `site/checks.py`.
- To build it yourself: `pip install -r site/requirements.txt`, then
  `sphinx-build site site/_build/html`.
