#!/bin/bash
# Weekly entry point, run from crontab on cron.hpc.ucar.edu (see README.md).
# The cron host only has 1 GB and no software (not even git), so this only
# submits run_mom_tests.pbs, which updates this repo, CESM and CrocoDash itself.
#
# CI_ROOT : holds the CESM and CrocoDash clones (default: /glade/work/$USER/croc_ci)
#           Which branches get tested is whatever those clones have checked out.
# MAILTO  : where PBS mails when the job ends (default: $USER@ucar.edu)
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
CI_ROOT=${CI_ROOT:-/glade/work/$USER/croc_ci}

cd "$HERE"
# Job logs go next to the clones, not into this repo.
mkdir -p "$CI_ROOT/logs"
/opt/pbs/bin/qsub -q main@desched1 -m ae -M "${MAILTO:-$USER@ucar.edu}" -o "$CI_ROOT/logs/" \
  -v UPDATE=1,PUBLISH=1,CESMROOT=$CI_ROOT/CESM,CROCODASH_SRC=$CI_ROOT/CrocoDash \
  run_mom_tests.pbs
