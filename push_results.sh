#!/bin/bash
# Push the result files in a directory to this repo's main branch, into DEST,
# which rebuilds the site:
#
#   DEST=integration MSG="..." push_results.sh <results-dir>
#
# integration/collect.pbs pushes a suite's results (testing.json and .xml with
# cesm_runs.json, or performance.json and .xml) to integration/; the data-access
# check pushes health.json to data_access/.
#
# Authenticates with the token that `gh auth login` stored in
# ~/.config/gh/hosts.yml; Derecho has no gh module, so gh itself isn't needed.
set -euo pipefail

RESULTS_DIR=$(cd "$1" && pwd)
REPO=https://github.com/CROCODILE-CESM/CrocoDashChecks
BRANCH=${BRANCH:-main}
DEST=${DEST:-.}
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
# The helper reads the token when git asks, so it never shows up in `ps`.
HELPER='!f() { echo username=x-access-token; awk '\''/oauth_token:/ {print "password=" $2; exit}'\'' ~/.config/gh/hosts.yml; }; f'
git_() { git -C "$WORK" -c credential.helper= -c credential.helper="$HELPER" "$@"; }

if git ls-remote --exit-code --heads "$REPO" "$BRANCH" >/dev/null; then
  git clone -q --depth 1 -b "$BRANCH" "$REPO" "$WORK"
else
  git init -q -b "$BRANCH" "$WORK"
  git_ remote add origin "$REPO"
fi

mkdir -p "$WORK/$DEST"
cp "$RESULTS_DIR"/* "$WORK/$DEST"/
git_ add -A
git_ diff --cached --quiet && exit 0
git_ commit -q -m "${MSG:-Test results $(date +%F)}"

# Several test jobs may finish at once: rebase onto whatever landed first.
for _ in 1 2 3 4 5; do
  git_ push -q origin "$BRANCH" && exit 0
  git_ pull -q --rebase origin "$BRANCH" || true
  sleep $((RANDOM % 20))
done
echo "Could not push results to $BRANCH" >&2
exit 1
