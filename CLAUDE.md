# CLAUDE.md

CrocoDashChecks checks CrocoDash end to end: weekly CESM runs (`cesm_runs/`), a daily
data-access check (`data_access/`), and performance snapshots (`performance/`). `site/build_site.py`
turns their JSON into two pages on GitHub Pages: the checks, and performance with its charts and fits. See README.md for what runs where.

## Rules

- **Keep it small.** One script per job; no packages, frameworks or config layers. MOM_interface's
  `testlist_mom.xml` decides which CESM tests run; don't add test lists here.
- **Status colors mark state only, always beside a text label.** Every number on the page comes from
  the JSON. A check older than `STALE_DAYS` in `site/build_site.py` shows as stale, because a
  schedule that stops running fails silently otherwise.
- **The jobs run from the CI clones in `/glade/work/$USER/croc_ci`** and reset them to their branch
  tips (`UPDATE=1`). PBS copies a job script when it's submitted, so a change to a `.pbs` file takes
  effect only once the clone has it: pull there after merging.
- **Keep `cron_submit.sh` scripts executable in git (100755):** the reset restores git's mode.
- Use black on Python before committing.

## Gotchas

- **`data_access/check.py` runs each access method in its own process group** and kills it at
  `VALIDATE_TIMEOUT`. A thread pool can't do this: leaving it waits for the thread, so one
  whole-file download held up every run.
- **A failing method's `detail` is its last error line,** because `validate_method` catches its own
  exceptions and returns False.
- **The weekly job pushes `cesm_runs.json` to `test-results`, not `main`,** so the site only picks it
  up on its next rebuild, at the latest after the next daily data-access push.
- **`performance/test_mapping.py` needs the `mom6_forge` env:** CrocoDash's nested mom6_forge lacks the
  runoff-mapping write-path fix (mom6_forge #125). Keep its boxes clear of the 0/360 seam.
- **MOM6 truncates `INPUTDIR` at 128 characters,** so keep `cesm_runs/` test paths short.
