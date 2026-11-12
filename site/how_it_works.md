# How it works

Every Monday at 02:00 MT, two jobs run against a fresh clone of CrocoDash `main`:

| Job | What it does | Where | Results, on `main` |
|---|---|---|---|
| Workflow | For every grid in the test matrix: `crocodash create`, then `crocodash process` for each forcing it turns on, each step timed; on grids marked `cesm_runs`, every regional SMS compset in MOM_interface's `testlist_mom.xml`, built and run | One Derecho node | `integration/workflow.json`, `workflow.xml`, `cesm_runs.json` |
| Data access | Calls every way CrocoDash fetches data | Casper | `data_access/health.json` |

## The test matrix

- [`integration/matrix.yaml`](https://github.com/CROCODILE-CESM/CrocoDashChecks/blob/main/integration/matrix.yaml):
  one row per grid, with the forcings to process on it (`bc`, `runoff`) and `cesm_runs: true`.
- [`integration/case.yaml`](https://github.com/CROCODILE-CESM/CrocoDashChecks/blob/main/integration/case.yaml):
  the CrocoDash case config every row starts from (coarse GEBCO, synthetic forcing); a row can
  change it under `case:`.
- Every row's case is a real case, kept after the run; a CESM row's other compsets reuse its
  grid, bathymetry and vertical grid files.
- To add a grid, add a row; to turn a step off, delete it from its row.
- A row with `cesm_runs: true` lists every forcing too, since the CESM runs build them all
  (`matrix.py` refuses a matrix that doesn't).
- ▲ or ▼ beside a step: it got more than 25% (and 5 s or 1 GB) slower or faster than the median
  of the last 4 runs, which the site reads from git history. Nothing shows otherwise.

## The weekly run

- One crontab line on `cron.hpc.ucar.edu` (`crontab -e` there) submits a small Casper job that
  clones this repo and runs `weekly.sh`, with the CESM checkout to use as its argument:

  ```
  0 2 * * 1 /opt/pbs/bin/qsub -q casper@casper-pbs -A NCGD0011 -l select=1:ncpus=1:mem=4GB -l walltime=00:30:00 -j oe -o /glade/derecho/scratch/$USER/crocodashchecks/ -- /bin/bash -c 'D=$(mktemp -d) && git clone -q https://github.com/CROCODILE-CESM/CrocoDashChecks $D && bash $D/weekly.sh /glade/u/home/$USER/work/installs/CESM_crocodashchecks' >> /glade/derecho/scratch/$USER/crocodashchecks/cron.log 2>&1
  ```
- The CESM checkout must be on CESM's `crocodash` branch with no local changes; the workflow
  fast-forwards it to the branch's tip before it starts.
- `weekly.sh` copies the clone to `/glade/derecho/scratch/$USER/crocodashchecks/<date>/` and
  submits both jobs from there; their logs go to its `logs/`. Runs older than four weeks are
  deleted.
- Each job clones CrocoDash `main`, runs, and pushes its results with your `gh` login's token.
  Each push rebuilds this site.
- The cases: `/glade/derecho/scratch/$USER/croc_tests/<grid>.<compset>.<run>/`, each with a
  `.log` beside it for the CESM runs.

## Running a check by hand

From a clone of this repo:

```bash
# the workflow; PYTEST_K=pole runs only the steps whose name matches "pole"
qsub -q main@desched1 -v CESMROOT=/path/to/CESM integration/workflow.pbs
# data access
qsub -q casper@casper-pbs data_access/check.pbs
```

- Add `CROCODASH_BRANCH=my-branch` to `-v` to test another CrocoDash branch, and `PUBLISH=1` to
  publish the results (full runs only).
- To run Python directly, `source crocodash_main.sh` first, or the `CrocoDash` env's own older
  CrocoDash is tested.

## This site

- `.github/workflows/publish.yml` rebuilds it on every push to `main`.
- The Status and Performance pages are notebooks (`site/*.ipynb`) that read the results files;
  edit them in Jupyter. Shared code is in `site/checks.py`.
- To build it yourself: `pip install -r site/requirements.txt`, then
  `sphinx-build site site/_build/html`.
