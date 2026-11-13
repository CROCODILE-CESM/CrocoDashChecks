# How it works

| Check | When | What it does | Where | Results, on `main` |
|---|---|---|---|---|
| Testing | Every Monday, 02:00 MT | Each testing row of the matrix: its case, made whole by `crocodash create` as a user makes it (every forcing processed); on rows marked `cesm_runs`, every regional SMS compset in MOM_interface's `testlist_mom.xml`, built and run | A Derecho develop job per row (64 cores; 4 at a time) | `integration/testing.json`, `testing.xml`, `cesm_runs.json` |
| Performance | First Monday of each month | Each performance row's case, configured, then each forcing it lists processed and timed on its own, plus the sweeps for the [fits](performance.ipynb) | A whole Derecho node per row | `integration/performance.json`, `performance.xml` |
| Data access | Every Monday | Calls every way CrocoDash fetches data | Casper | `data_access/health.json` |

## The matrix

- [`integration/matrix.yaml`](https://github.com/CROCODILE-CESM/CrocoDashChecks/blob/main/integration/matrix.yaml):
  one row per grid, in two parts: `testing` (places CrocoDash must work; a row can add
  `cesm_runs: true`) and `performance` (sizes, for the fits; a row lists the forcings to time
  on it, `bc` and `runoff`).
- [`integration/case.yaml`](https://github.com/CROCODILE-CESM/CrocoDashChecks/blob/main/integration/case.yaml):
  the CrocoDash case config every row starts from (coarse GEBCO, synthetic forcing); a row can
  change it under `case:`.
- Every row's case is a real case, kept after the run; a CESM row's other compsets reuse its
  grid, bathymetry and vertical grid files.
- To add a grid, add a row; to turn CESM runs or a timed forcing off, delete it from its row.
- ▲ or ▼ beside a step: it got more than 25% (and 5 s or 1 GB) slower or faster than the median
  of its suite's last 4 runs, which the site reads from git history. Nothing shows otherwise.

## The schedule

- One crontab line on `cron.hpc.ucar.edu` (`crontab -e` there) submits a small Casper job that
  clones this repo and runs `weekly.sh`, with the CESM checkout to use as its argument:

  ```
  0 2 * * 1 /opt/pbs/bin/qsub -q casper@casper-pbs -A NCGD0011 -l select=1:ncpus=1:mem=4GB -l walltime=00:30:00 -j oe -o /glade/derecho/scratch/$USER/crocodashchecks/ -- /bin/bash -c 'D=$(mktemp -d) && git clone -q https://github.com/CROCODILE-CESM/CrocoDashChecks $D && bash $D/weekly.sh /glade/u/home/$USER/work/installs/CESM_crocodashchecks' >> /glade/derecho/scratch/$USER/crocodashchecks/cron.log 2>&1
  ```
- `weekly.sh` brings the CESM checkout to the tip of CESM's `crocodash` branch (it must have no
  local changes), then submits one job per row, all testing the same CrocoDash `main` commit.
  Once a suite's jobs have all ended, `integration/collect.pbs` merges their results and
  pushes them, which rebuilds this site.
- Each run: `/glade/derecho/scratch/$USER/crocodashchecks/<date>/` (its results by row, and
  `logs/`), deleted after four weeks. The cases:
  `/glade/derecho/scratch/$USER/croc_tests/<grid>.<compset>.<run>/`.

## Running a check by hand

From a clone of this repo:

```bash
# one row; PYTEST_K=test_create runs only the steps whose name matches
qsub -q main@desched1 -v ROW=labrador,CESMROOT=/path/to/CESM integration/workflow.pbs
# data access
qsub -q casper@casper-pbs data_access/check.pbs
# everything, as on a Monday, with the performance rows too
PERFORMANCE=1 bash weekly.sh /path/to/CESM
```

- A row's results go to `integration/results/<row>/`. Add `CROCODASH_BRANCH=my-branch` to `-v`
  to test another CrocoDash branch.
- To run Python directly, `source crocodash_main.sh` first, or the `CrocoDash` env's own older
  CrocoDash is tested.

## This site

- `.github/workflows/publish.yml` rebuilds it on every push to `main`.
- The Status and Performance pages are notebooks (`site/*.ipynb`) that read the results files;
  edit them in Jupyter. Shared code is in `site/checks.py`.
- To build it yourself: `pip install -r site/requirements.txt`, then
  `sphinx-build site site/_build/html`.
