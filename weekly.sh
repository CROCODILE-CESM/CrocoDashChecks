#!/bin/bash
# Every check, from a fresh clone of this repo:
#
#   bash weekly.sh <CESMROOT>
#
# CESMROOT is a checkout of CROCODILE-CESM/CESM branch crocodash with no local
# changes; this brings it to the branch's tip first, before any job builds from
# it. The one crontab line on cron.hpc.ucar.edu (site/how_it_works.md) starts a
# small Casper job that clones this repo into a temporary directory and runs
# this script from it every Monday; the cron host itself has no git.
#
# It submits, from this run's own directory:
#   testing      every week: one Derecho develop job per testing row of
#                integration/matrix.yaml (workflow.pbs), then collect.pbs
#                to merge and publish their results once they have all ended
#   performance  the same for the performance rows, each on a whole main node,
#                on the first Monday of each month
#   data access  data_access/check.pbs on Casper
# Every row's job tests the same CrocoDash main commit (its tip now).
#
#   /glade/derecho/scratch/$USER/crocodashchecks/<date>/   (deleted after four weeks)
#     CrocoDashChecks/   this repo as of this run, which the jobs run from
#     results/           each suite's results, one directory per row
#     logs/              the jobs' logs
#
# PERFORMANCE : if set, run the performance rows whatever the date
# MAILTO      : where PBS mails when a job ends (default: $USER@ucar.edu)
# QSUB        : the qsub to use (default: /opt/pbs/bin/qsub); QSUB=echo only
#               prints the submissions (CESMROOT is still brought to its tip)
set -euo pipefail

CESMROOT=${1:?usage: weekly.sh <CESMROOT>}
ROOT=/glade/derecho/scratch/$USER/crocodashchecks
RUN=$ROOT/$(date +%F_%H%M)
QSUB=${QSUB:-/opt/pbs/bin/qsub}
OPTS=(-m ae -M "${MAILTO:-$USER@ucar.edu}" -o "$RUN/logs/")

mkdir -p "$RUN/logs"
cp -r "$(cd "$(dirname "$0")" && pwd)" "$RUN/CrocoDashChecks"
cd "$RUN/CrocoDashChecks"

# NCAR's default environment: git-fleximod and matrix.py need a newer Python
# than the system's. /etc/profile isn't written for set -eu.
set +eu
source /etc/profile >/dev/null 2>&1
set -eu

# CESM at the tip of crocodash.
if [ -n "$(git -C "$CESMROOT" status --porcelain)" ]; then
  echo "$CESMROOT has local changes; not using it" >&2
  exit 1
fi
git -C "$CESMROOT" fetch -q origin crocodash
if [ "$(git -C "$CESMROOT" rev-parse HEAD)" != "$(git -C "$CESMROOT" rev-parse origin/crocodash)" ]; then
  echo "Updating $CESMROOT to the tip of crocodash"
  git -C "$CESMROOT" merge -q --ff-only origin/crocodash
  (cd "$CESMROOT" && ./bin/git-fleximod update)
fi

COMMIT=$(git ls-remote https://github.com/CROCODILE-CESM/CrocoDash refs/heads/main | cut -f1)
RUN_ID=$(date +%Y%m%d_%H%M)  # names the cases
SUITES=(testing)
if [ "$(date +%-d)" -le 7 ] || [ -n "${PERFORMANCE:-}" ]; then
  SUITES+=(performance)
fi
for suite in "${SUITES[@]}"; do
  # Testing rows are small: 64 cores of a shared develop node, which starts at
  # once (a user may run 256 cores there, so 4 rows at a time). Performance rows
  # get a whole main node each (workflow.pbs's own -q and -l), for clean timings.
  if [ "$suite" = testing ]; then
    WHERE=(-q develop@desched1 -l select=1:ncpus=64:mpiprocs=64:mem=120GB -l place=pack:shared)
  else
    WHERE=(-q main@desched1)
  fi
  jobs=()
  for row in $(python3 integration/matrix.py "$suite"); do
    jobs+=("$($QSUB "${WHERE[@]}" -N "$row" "${OPTS[@]}" \
      -v "ROW=$row,CESMROOT=$CESMROOT,CROCODASH_COMMIT=$COMMIT,RUN_ID=$RUN_ID,RESULTS=$RUN/results/$suite/$row" \
      integration/workflow.pbs)")
    echo "$row: ${jobs[-1]}"
  done
  $QSUB -q develop@desched1 -N "collect_$suite" "${OPTS[@]}" \
    -W depend=afterany:"$(IFS=:; echo "${jobs[*]}")" \
    -v "SUITE=$suite,RESULTS=$RUN/results/$suite,PUBLISH=1" integration/collect.pbs
done
$QSUB -q casper@casper-pbs "${OPTS[@]}" -v PUBLISH=1 data_access/check.pbs

find "$ROOT" -mindepth 1 -maxdepth 1 -type d -name '20*' -mtime +27 -exec rm -rf {} +
