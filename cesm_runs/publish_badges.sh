#!/bin/bash
# Push the badge JSONs written by `run_mom_tests.py --badge-dir` to this repo's
# `test-results` branch, which the README's shields.io badges read.
#
#   publish_badges.sh <badge-dir>
#
# Authenticates with the token that `gh auth login` stored in
# ~/.config/gh/hosts.yml; Derecho has no gh module, so gh itself isn't needed.
set -euo pipefail

BADGE_DIR=$(cd "$1" && pwd)
REPO=https://github.com/CROCODILE-CESM/CrocoDashChecks
BRANCH=test-results
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

cp "$BADGE_DIR"/*.json "$WORK"/
git_ add -A
git_ diff --cached --quiet && exit 0
git_ commit -q -m "Test results $(date +%F)"

# Several test jobs may finish at once: rebase onto whatever landed first.
for _ in 1 2 3 4 5; do
  git_ push -q origin "$BRANCH" && exit 0
  git_ pull -q --rebase origin "$BRANCH" || true
  sleep $((RANDOM % 20))
done
echo "Could not push badges to $BRANCH" >&2
exit 1
