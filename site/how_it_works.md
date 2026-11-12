# How it works

CrocoDashChecks runs three checks on NCAR's systems and publishes their results here.

| Check | What it does | Where | When | Results |
|---|---|---|---|---|
| [The workflow](#the-workflow) | Builds every grid in the test matrix with its bathymetry, runs the forcings turned on for each, and times every step | One Casper node | Mondays 02:00 MT | `integration/workflow.json` and `workflow.xml` on `main` |
| [Weekly CESM runs](integration.md) | Builds each regional SMS test in MOM_interface's `testlist_mom.xml` with CrocoDash on each grid the test matrix turns the CESM runs on for, then runs it in CESM | One Derecho node | Mondays 02:00 MT | `cesm_runs.json` on the `test-results` branch |
| Data access | Calls every way CrocoDash fetches data (every product's access methods), for real | Casper | Daily 05:00 MT | `data_access/health.json` on `main` |

The first two live in `integration/`, the last in `data_access/`. To run any of them yourself, see
[Running the checks by hand](#by-hand).

## The test matrix

[`matrix.yaml`](https://github.com/CROCODILE-CESM/CrocoDashChecks/blob/main/integration/matrix.yaml) has one
row per grid: a latitude/longitude box, or a polar stereographic square centred on a pole. Each
row lists the forcings to run on its grid (by their `crocodash process` flag: `bc` for open
boundaries, `runoff` for runoff mapping) and whether the weekly CESM runs build cases on it. To
turn something on for a grid, add it to the row; to turn it off, delete it; to stop building a
grid at all, delete its row. The [Status page](index.ipynb) shows the matrix with every step's
latest result.

Every case starts from
[`case.yaml`](https://github.com/CROCODILE-CESM/CrocoDashChecks/blob/main/integration/case.yaml): a
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

[`integration/test_workflow.py`](https://github.com/CROCODILE-CESM/CrocoDashChecks/blob/main/integration/test_workflow.py)
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
go to `integration/workflow.json` (pytest-benchmark); what passed, failed or was skipped, and
why, goes to `integration/workflow.xml` (pytest's own JUnit report), which is how the site can
show a failure and not just a missing number.

## Which CrocoDash gets tested

Every check tests the tip of CrocoDash `main`, and the weekly runs use the tip of CESM's
`crocodash` branch, with the MOM_interface regional tag it pins. `crocodash_main.sh` clones
CrocoDash fresh, with its submodules, puts that clone first on `PYTHONPATH`, and deletes it
when the job (or your shell) exits. Every scheduled job sources it, and you should too before
running anything by hand. Each job records the branch and commit it tested, and the
[Status page](index.ipynb) shows them. The `CrocoDash` conda env supplies only the
dependencies.

To test another branch, submit the job yourself with `CROCODASH_BRANCH` set, e.g.
`qsub -v CESMROOT=...,CROCODASH_BRANCH=my-branch integration/run_mom_tests.pbs`.

## How a scheduled run starts

1. **The crontab on `cron.hpc.ucar.edu`** has two lines: the weekly one submits both weekly
   jobs (the workflow and the CESM runs), the daily one the data-access check. The cron host has
   no software (not even git), so each `cron_submit.sh` only runs `qsub`:

   ```
   0 2 * * 1 /glade/work/$USER/croc_ci/CrocoDashChecks/integration/cron_submit.sh >> /glade/work/$USER/croc_ci/cron.log 2>&1
   0 5 * * * /glade/work/$USER/croc_ci/CrocoDashChecks/data_access/cron_submit.sh >> /glade/work/$USER/croc_ci/cron.log 2>&1
   ```

   Edit it with `ssh cron.hpc.ucar.edu` and then `crontab -e`.
2. **Each job** (`integration/workflow.pbs`, `integration/run_mom_tests.pbs` or
   `data_access/check.pbs`) first resets its clone of this repo to `main`. The CESM runs also
   reset the CESM clone and run `git-fleximod update`. Then it clones CrocoDash and runs the check.
3. **It publishes its results** with `push_results.sh`, using the token from your
   `gh` login. The CESM runs push `cesm_runs.json` to the `test-results` branch. The workflow
   pushes `integration/workflow.json` and `workflow.xml`, and the daily check
   `data_access/health.json`, to `main`, and those pushes rebuild this site.

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

(by-hand)=
## Running the checks by hand

Everything runs in the `CrocoDash` conda env (which has pytest-benchmark installed for the
workflow), from a checkout of this repo:

```bash
git clone https://github.com/CROCODILE-CESM/CrocoDashChecks
cd CrocoDashChecks
module load conda
conda activate CrocoDash
```

The job scripts (`*.pbs`) clone CrocoDash `main` fresh themselves. To run Python directly, clone it
first with `source crocodash_main.sh`, or the env's own (older) CrocoDash gets tested. To test
another CrocoDash branch, set `CROCODASH_BRANCH=my-branch` before sourcing it, or add
`-v CROCODASH_BRANCH=my-branch` to a `qsub`.

### The workflow: grids and forcings

It needs a big node (full GEBCO on the 40° square takes ~65 GB, runoff mapping on the
Indo-Pacific at rmax 80 km ~80 GB) and about two hours. Submit it from the repo root:

```bash
qsub -q casper@casper-pbs integration/workflow.pbs                                 # every step
qsub -q casper@casper-pbs -v PYTEST_ARGS="-k pole" integration/workflow.pbs        # steps whose name has "pole"
qsub -q casper@casper-pbs -v PYTEST_ARGS="-k test_grid" integration/workflow.pbs   # only build the grids
```

A step's name is its test and its grid, like `test_bc[north_pole]`; list them all with
`pytest --collect-only -q integration/test_workflow.py`. The job writes
`integration/workflow.json` (timings) and `integration/workflow.xml` (what passed, failed or was
skipped, and why) in your checkout, and its log, `crocodashchecks_workflow.o<job id>`, where you
submitted it. Build the site (below) to see them. The weekly run publishes itself; a hand run publishes
nothing unless you add `-v PUBLISH=1` (full runs only: a run with `-k` holds only its own steps).

### The weekly CESM runs

They need a checkout of CESM's `crocodash` branch, and run on one Derecho node:

```bash
git clone -b crocodash https://github.com/CROCODILE-CESM/CESM ~/CESM_crocodash
(cd ~/CESM_crocodash && ./bin/git-fleximod update)

cd integration
python run_mom_tests.py --cesmroot ~/CESM_crocodash --test-root /tmp/x --dry-run   # list the tests
qsub -v CESMROOT=$HOME/CESM_crocodash run_mom_tests.pbs                             # run them all
qsub -v "CESMROOT=$HOME/CESM_crocodash,EXTRA=--grids north_pole --only GR_JRA" run_mom_tests.pbs
```

The last one runs only the tests whose name contains `GR_JRA`, on the `north_pole` grid. From
Casper, add `-q main@desched1`. A hand run publishes nothing (the weekly one sets `PUBLISH=1`):
each test's directory is in `/glade/derecho/scratch/$USER/croc_tests/`, and
`cs.status.<test id>` there sums them up. More: [Integration](integration.md).

### Data access

```bash
source crocodash_main.sh
python data_access/check.py                       # writes data_access/health.json
qsub -q casper@casper-pbs data_access/check.pbs   # or as a Casper job, which clones CrocoDash itself
```

### MOM6 speed vs. tasks

`integration/mom6_scaling.json` holds a hand-run NTASKS_OCN sweep; its scripts are in the CROC
monorepo's `dev/scaling_test/`.
