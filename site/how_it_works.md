# How it works

CrocoDashChecks runs three checks on NCAR's systems and publishes their results here.

| Check | What it does | Where | When | Results |
|---|---|---|---|---|
| [The workflow](#the-workflow) | Builds every grid in the test matrix with its bathymetry, runs the forcings turned on for each, and times every step | One Casper node | By hand | `performance/workflow.json` and `workflow.xml` on `main` |
| [Weekly CESM runs](cesm_runs.md) | Builds each regional SMS test in MOM_interface's `testlist_mom.xml` with CrocoDash on each grid the test matrix turns the CESM runs on for, then runs it in CESM | One Derecho node | Mondays 02:00 MT | `cesm_runs.json` on the `test-results` branch |
| Data access | Calls every way CrocoDash fetches data (every product's access methods), for real | Casper | Daily 05:00 MT | `data_access/health.json` on `main` |

## The test matrix

[`matrix.yaml`](https://github.com/CROCODILE-CESM/CrocoDashChecks/blob/main/matrix.yaml) has one
row per grid: a latitude/longitude box, or a polar stereographic square centred on a pole. Each
row lists the forcings to run on its grid (by their `crocodash process` flag: `bc` for open
boundaries, `runoff` for runoff mapping) and whether the weekly CESM runs build cases on it. To
turn something on for a grid, add it to the row; to turn it off, delete it; to stop building a
grid at all, delete its row. The [Status page](index.ipynb) shows the matrix with every step's
latest result.

Every case starts from
[`case.yaml`](https://github.com/CROCODILE-CESM/CrocoDashChecks/blob/main/case.yaml): a
CrocoDash case config, what `crocodash create --config` reads, without the grid. A row adds its
grid, and can change anything else for itself under `case:` (the `pacific_*` squares up to 40°
use it to switch to full-resolution GEBCO). Its bathymetry is GEBCO coarsened 8× (1/30°), since
full GEBCO over a polar cap needs hundreds of GB, and its forcing is synthetic, so nothing is
downloaded.

The rows, in three groups:

| Rows | Grids | Why |
|---|---|---|
| `labrador`, `equator_0e`, `equator_180e`, `north_pole`, `south_pole` | A coast, both seams and both poles, at 1/4° or 100 km | Places that break things: sea ice and rivers, the prime meridian and the antimeridian, and grids on a projection over a pole |
| `pacific_2p5deg` … `pacific_160deg` | Squares of open ocean from 2.5° to 160°, at 0.1° | Sizes, for the open-boundary and bathymetry fits |
| `gulf_1deg` … `indo_pacific` | Coasts from a 1° box to the Indo-Pacific, at 1/12°, and the Gulf of Mexico at 1/4°–1/25° | Sizes and resolutions, for the runoff-mapping fits |

(the-workflow)=
## The workflow

[`performance/test_workflow.py`](https://github.com/CROCODILE-CESM/CrocoDashChecks/blob/main/performance/test_workflow.py)
runs CrocoDash's workflow on every row, and times it: it is an integration test and a benchmark
in one.

1. **The grid.** `test_grid` builds the row's grid, bathymetry and vertical grid from its case
   config with CrocoDash's own builders, as `crocodash create` does, and writes the files a case
   gets. It checks that no depths are missing and that there is some ocean. Each grid is built
   once; every forcing on that row reuses it.
2. **The forcings.** `test_bc` and `test_runoff` run each forcing the row turns on through
   CrocoDash's own configurators (configure, then process), as `crocodash process` would,
   without a CESM case. If a grid fails to build, its forcings are skipped.
3. **The sweeps.** A few more cases vary what isn't a grid, on one or two rows each, for the
   [Performance](performance.ipynb) page's fits: open boundaries by source resolution, days and
   workers, and runoff by smoothing radius.

Every step runs in its own forked process and is timed once, with its peak memory. The timings
go to `performance/workflow.json` (pytest-benchmark); what passed, failed or was skipped, and
why, goes to `performance/workflow.xml` (pytest's own JUnit report), which is how the site can
show a failure and not just a missing number.

## Which CrocoDash gets tested

Every check tests the tip of CrocoDash `main`, and the weekly runs use the tip of CESM's
`crocodash` branch, with the MOM_interface regional tag it pins. `crocodash_main.sh` clones
CrocoDash fresh, with its submodules, puts that clone first on `PYTHONPATH`, and deletes it
when the job (or your shell) exits. Both scheduled jobs source it, and you should too before
running anything by hand. Each job records the branch and commit it tested, and the
[Status page](index.ipynb) shows them. The `CrocoDash` conda env supplies only the
dependencies.

To test another branch, submit the job yourself with `CROCODASH_BRANCH` set, e.g.
`qsub -v CESMROOT=...,CROCODASH_BRANCH=my-branch cesm_runs/run_mom_tests.pbs`.

## How a scheduled run starts

1. **The crontab on `cron.hpc.ucar.edu`** runs a `cron_submit.sh` script. The cron host has
   no software (not even git), so that script only runs `qsub`:

   ```
   0 2 * * 1 /glade/work/$USER/croc_ci/CrocoDashChecks/cesm_runs/cron_submit.sh >> /glade/work/$USER/croc_ci/cron.log 2>&1
   0 5 * * * /glade/work/$USER/croc_ci/CrocoDashChecks/data_access/cron_submit.sh >> /glade/work/$USER/croc_ci/cron.log 2>&1
   ```

   Edit it with `ssh cron.hpc.ucar.edu` and then `crontab -e`.
2. **The job** (`cesm_runs/run_mom_tests.pbs` or `data_access/check.pbs`) first resets its
   clone of this repo to `main`. The weekly job also resets the CESM clone and runs
   `git-fleximod update`. Then it clones CrocoDash and runs the check.
3. **It publishes its results** with `cesm_runs/push_results.sh`, using the token from your
   `gh` login. The weekly runs push `cesm_runs.json` to the `test-results` branch. The daily
   check pushes `data_access/health.json` to `main`, and that push rebuilds this site.

:::{important}
PBS copies a job script when the job is submitted, before the job updates its clone. So a
change to a `.pbs` file only takes effect once the CI clone has it: after merging, run
`git -C /glade/work/$USER/croc_ci/CrocoDashChecks pull`.
:::

## Where things are

| What | Where |
|---|---|
| CI clones the jobs run from (reset every run, so don't edit them) | `/glade/work/$USER/croc_ci/`: this repo and CESM's `crocodash` branch |
| Cron output | `/glade/work/$USER/croc_ci/cron.log` |
| Job logs | `/glade/work/$USER/croc_ci/logs/` |
| Weekly test directories | `/glade/derecho/scratch/$USER/croc_tests/` |
| Credentials the data-access check uses | your own: `~/.cdsapirc`, `~/.copernicusmarine` |

## How this site is built

`.github/workflows/publish.yml` rebuilds the site on every push to `main`:

1. it fetches `cesm_runs.json` from the `test-results` branch;
2. `sphinx-build` runs the page notebooks ([Status](index.ipynb) and
   [Performance](performance.ipynb)), which read the results JSON and draw the tables and
   charts;
3. `site/write_badges.py` writes the README's two badges from the same counts.

The two pages read every result from the files above; the matrix's names and layout come from
`matrix.yaml` itself.

To build it yourself:

```bash
pip install -r site/requirements.txt
sphinx-build site site/_build/html
python site/write_badges.py
# open site/_build/html/index.html
```

To change a page, open its notebook (`site/index.ipynb` or `site/performance.ipynb`) in
Jupyter, run it, and edit it like any notebook. Clear its outputs before committing: the
build reruns it anyway. Code that both pages need is in `site/checks.py`.

## Running a check by hand

Everything here runs in the `CrocoDash` conda env (which has pytest-benchmark installed for the
workflow). Start every hand run with a fresh clone of CrocoDash `main`:

```bash
conda activate CrocoDash
source crocodash_main.sh
```

**Data access**, on GLADE:

```bash
python data_access/check.py                     # writes data_access/health.json
qsub -q casper@casper-pbs data_access/check.pbs  # or as a Casper job, with a fresh clone of main
```

**Weekly CESM runs**: see [Weekly CESM runs](cesm_runs.md).

**The workflow** needs a big node: full GEBCO on the 40° square takes ~45 GB, and runoff
mapping on the Indo-Pacific at rmax 80 km ~90 GB. Submit it from the repo root; it clones
CrocoDash `main` itself, takes a few hours, and writes `performance/workflow.json` and
`workflow.xml` in your checkout:

```bash
qsub -q casper@casper-pbs performance/run.pbs
qsub -q casper@casper-pbs -v PYTEST_ARGS="-k pole" performance/run.pbs   # only some steps
```

Commit the two files to publish them.


`performance/mom6_scaling.json` holds a hand-run NTASKS_OCN sweep; its scripts are in the CROC
monorepo's `dev/scaling_test/`.
