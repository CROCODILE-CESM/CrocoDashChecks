#!/bin/bash
# Daily entry point, run from crontab on cron.hpc.ucar.edu (see README.md).
# The cron host only has 1 GB and no software (not even git), so this only
# submits data_access.pbs to Casper, which has GLADE and the internet.
#
# CI_ROOT : holds the CrocoDash clone (default: /glade/work/$USER/croc_ci)
# MAILTO  : where PBS mails if the job aborts (default: $USER@ucar.edu)
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
CI_ROOT=${CI_ROOT:-/glade/work/$USER/croc_ci}

cd "$HERE"
mkdir -p "$CI_ROOT/logs"
/opt/pbs/bin/qsub -q casper@casper-pbs -m a -M "${MAILTO:-$USER@ucar.edu}" -o "$CI_ROOT/logs/" \
  -v UPDATE=1,PUBLISH=1,CROCODASH_SRC=$CI_ROOT/CrocoDash \
  data_access.pbs
