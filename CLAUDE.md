# CLAUDE.md

CrocoDashChecks checks CrocoDash end to end, in two folders: `integration/` (the matrix of
grids, and `test_workflow.py`, which takes a row through the CrocoDash CLI on a real case and
builds and runs CESM on the rows marked for it, one Derecho job per row) and `data_access/` (every
data access method, on Casper). The matrix has two suites: `testing` rows run every Monday,
`performance` rows (sizes and sweeps, for the fits) on the first Monday of each month. All of it
starts from `weekly.sh <CESMROOT>`, run by one crontab line. Shared job
scripts (`weekly.sh`, `crocodash_main.sh`, `push_results.sh`) are at the root. `site/` is a Sphinx
site on GitHub Pages; its Status and Performance pages are notebooks that read that JSON. How it all
runs: `site/how_it_works.md`.

## Where things live

| What | Where |
|---|---|
| Dev checkout (edit here, or in a worktree) | `dev/CrocoDashChecks/` in the CROC monorepo |
| Each weekly run (a fresh clone of this repo, results by suite and row, job logs; 4 weeks kept) | `/glade/derecho/scratch/$USER/crocodashchecks/<date>/` |
| The CESM checkout (an argument: `weekly.sh <CESMROOT>`, `qsub -v CESMROOT=`) | the user's: `~/work/installs/CESM_crocodashchecks`, kept clean at `crocodash`'s tip by `weekly.sh`; never their `CESM_crocodash` |
| The cases (kept) | `/glade/derecho/scratch/$USER/croc_tests/<grid>.<compset>.<run>/` |
| Data the data-access check reads (not a clone; keep it) | `/glade/work/$USER/croc_ci/inputs/` |
| The CrocoDash tested | a fresh clone of `main` per job, at the commit `weekly.sh` pins (`CROCODASH_COMMIT`; `CROCODASH_BRANCH` overrides the branch), deleted when the job ends |
| Crontab | `cron.hpc.ucar.edu`; read it with `ssh cron.hpc.ucar.edu crontab -l`; only the user edits it |
| Cron and job logs | `/glade/derecho/scratch/$USER/crocodashchecks/cron.log`, each run's `logs/` |
| Results | `integration/testing.json`, `testing.xml`, `cesm_runs.json`, `integration/performance.json`, `performance.xml` and `data_access/health.json` on `main` |
| Published site | <https://crocodile-cesm.github.io/CrocoDashChecks/>, built by `.github/workflows/publish.yml` |

Every job records the CrocoDash branch and commit it tested (`crocodash` in `cesm_runs.json` and
`health.json`, properties in `testing.xml`/`performance.xml`), and the Status page shows them.

## Rules

- **Everything runs in the `CrocoDash` conda env** (pytest-benchmark installed into it). Don't add
  other dependencies (the site's own build packages in `site/requirements.txt` are the exception:
  CI only).
- **Always test a fresh pull:** CrocoDash `main` via `source crocodash_main.sh` (every job does; do it
  before any hand run too), and CESM's `crocodash` branch tip with its pinned MOM_interface regional
  tag (`weekly.sh` fast-forwards CESMROOT once, before any row's job builds from it; both it and
  `workflow.pbs` refuse a CESMROOT with local changes).
- **Use the real CLI, never MCP servers or the container:** this runs from cron, so every step is a
  `crocodash` command (called as `CrocoDash.cli.main` in a forked child) or a CIME script.
- **The matrix is `integration/matrix.yaml`, one row per grid, in two suites** (`testing`,
  `performance`; read by `matrix.py`). Testing stays small: places CrocoDash must work, with
  every step. Performance holds only the sizes and sweeps a Performance fit needs. Every row is
  independent: its own job, its own case. Every case starts from `case.yaml`, and
  `case.yaml` is a CrocoDash case config without its grid. A row gives its grid, any
  changes to `case.yaml`, the forcings to run (`crocodash process` flags) and `cesm_runs`. Add
  grids there, never inside a test; a new forcing needs a step in `test_workflow.py` and its flag
  in `matrix.FORCINGS`. A `cesm_runs` row must list every forcing, since the CESM runs build
  them all (GLOFAS runoff needs its map); `matrix.py` asserts it.
- **The workflow is one file, `integration/test_workflow.py`, run one row at a time (`ROW`):**
  `test_create` makes the row's case (`crocodash create --configure-only`, profiled into
  grid/topo/vgrid/case), `test_bc` and
  `test_runoff` run `crocodash process` on it, and `test_cesm` builds and runs every testlist
  compset on `cesm_runs` rows (other compsets reuse the row case's grid files). Sweeps run
  `crocodash process --config` on an edited copy of a row case's forcing config. Every step runs in
  a forked child; its timing goes to the row's `workflow.json`, its pass/fail/skip with the reason
  to `workflow.xml` (pytest's junit), and the CESM phases to `cesm_runs.json`. `collect.pbs`
  merges a suite's rows into `integration/<suite>.json` and `.xml` (and `cesm_runs.json`).
- **Keep it small.** One script per job; no packages, frameworks or config layers. MOM_interface's
  `testlist_mom.xml` decides which CESM tests run; don't add test lists here.
- **The site is Markdown and notebooks, never hand-written HTML, CSS or JS** (the owner can't read
  them). Charts are matplotlib cell outputs; Sphinx runs the notebooks on every build and shows
  only their outputs, not their code (`nb_remove_code_source`). Commit notebooks without outputs;
  edit them as notebooks (no generator scripts). Shared helpers go in `site/checks.py`, page logic stays in
  the page's notebook. `site/requirements.txt` is pinned; bump it on purpose.
- **Keep the Status page terse and glanceable:** the matrix shows marks only (✅ ❌ ⬜ ⚠️, shapes,
  never color alone) with a one-line legend; tables are compact (`checks.table`). Every number
  on the site comes from the JSON. A check older than `STALE_DAYS` in `site/checks.py` shows as
  stale, because a schedule that stops running fails silently otherwise.
- **Keep the anchors other pages link to:** `#cesm` and `#data-access` (README badges) and
  `#mom6-scaling` (the gallery's `ocean_only` notebook) on the Status page.
- **Nothing is kept between weekly runs:** the crontab line clones this repo fresh and runs
  `weekly.sh`, which copies the clone into that run's directory and submits every job from there,
  so whatever is on `main` on Monday runs. Keep the crontab line itself minimal (clone, then
  `weekly.sh`); everything else belongs in `weekly.sh`.
- Use black on Python and the notebooks (`black[jupyter]`) before committing. Build the site with
  `sphinx-build --fail-on-warning site site/_build/html`, as CI does.

## Gotchas

- **`data_access/check.py` runs each access method in its own process group** and kills it at
  `VALIDATE_TIMEOUT`. A thread pool can't do this: leaving it waits for the thread, so one
  whole-file download held up every run.
- **A failing method's `detail` is its last error line,** because `validate_method` catches its own
  exceptions and returns False.
- **`crocodash create` needs Derecho** (it runs `case.setup`, which doesn't complete on Casper), so
  every row's job does: one node each, ~80 GB at the most (runoff on `indo_pacific` at rmax 80 km;
  full GEBCO on `pacific_40deg` ~65 GB and 22 min). Never on a login node.
- **A CESM test is ~20 min, almost all start-up:** DATM reading JRA's time bounds (~6 min) and
  DROF mapping GLOFAS (~4.5 min); the 2-day run is under a minute. A `cesm_runs` row's job is
  its 5 compsets in a row, so it is the longest (~2 h).
- **Testing rows run on `develop`, 64 cores each; performance rows on whole `main` nodes.** `main`
  can queue for hours; `develop` starts at once but runs at most 256 cores per user (`cpudev`), so
  4 testing rows at a time (the 5th starts when a short one ends) and nothing else of the user's.
- **A test with no cases on a row is collected as `test_x[NOTSET]`;** `workflow.pbs` deselects it
  (`-k "not NOTSET"`), or it would show as a skipped step.
- **`/etc/profile` isn't `set -e` safe** (`weekly.sh` sources it for a Python new enough for
  `git-fleximod`; the cron host's is 3.6), and **an apostrophe inside `${VAR:?message}` breaks
  bash's parsing** of the whole script; `bash -n` each script on its own.
- **`qsub -v` strips quotes,** so a multi-word pytest `-k` goes in `PYTEST_K`, which the job passes
  as one argument.
- **A step on a row whose case failed to create is skipped, not failed:** `equator_180e` fails
  at `test_create` (mom6_forge #173, the GEBCO ±180° gap), so its forcings show as skipped and its
  CESM tests fail at CREATE_NEWCASE.
- **The `CrocoDash` env imports its own installed CrocoDash** (the 2026 workshop checkout), not
  `main`, unless `crocodash_main.sh` was sourced first.
- **MOM6 truncates `INPUTDIR` at 128 characters,** so keep the CESM runs' test paths short.
- **The speed-change marks read past runs from git history** (`checks.past_results`: each
  run's commit of `integration/<suite>.json`), so `publish.yml` checks out with
  `fetch-depth: 0`, and `main`'s history must never be squashed or rewritten.
