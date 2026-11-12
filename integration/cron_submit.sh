#!/bin/bash
# Weekly entry point, run from crontab on cron.hpc.ucar.edu (see README.md).
# Submits both weekly jobs: the CESM runs (run_mom_tests.pbs, on Derecho) and
# the workflow (workflow.pbs, on Casper). The cron host only has 1 GB and no
# software (not even git), so this only runs qsub; each job updates this repo
# (and CESM), clones CrocoDash main, and publishes its results itself.
#
# CI_ROOT : holds the CESM clone and the job logs (default: /glade/work/$USER/croc_ci)
# MAILTO  : where PBS mails when a job ends (default: $USER@ucar.edu)
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
CI_ROOT=${CI_ROOT:-/glade/work/$USER/croc_ci}
MAIL=(-m ae -M "${MAILTO:-$USER@ucar.edu}")

cd "$HERE"
# Job logs go next to the clones, not into this repo.
mkdir -p "$CI_ROOT/logs"
/opt/pbs/bin/qsub -q main@desched1 "${MAIL[@]}" -o "$CI_ROOT/logs/" \
  -v UPDATE=1,PUBLISH=1,CESMROOT=$CI_ROOT/CESM \
  run_mom_tests.pbs
/opt/pbs/bin/qsub -q casper@casper-pbs "${MAIL[@]}" -o "$CI_ROOT/logs/" \
  -v UPDATE=1,PUBLISH=1 \
  workflow.pbs
