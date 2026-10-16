#!/usr/bin/env bash
# Officials Sign-In: let the tablet's repo follow a history rewrite of main.
#
# The owner asked for main's history to be rewritten to remove personal data from
# old commits. The files on main stay the same; only commit IDs change. The device
# agent updates with `git pull --ff-only`, which refuses a rewritten branch, so this
# task waits (in the foreground, at most 8 minutes) until the rewrite is on GitHub,
# then moves the tablet's main to the rewritten copy of the same commit (same author
# time and subject) with `git reset --keep`, which never discards local changes.
# Nothing is restarted. If no rewrite is seen in time, it changes nothing.
set -uo pipefail
CHECK_SECONDS=10
WAIT_SECONDS=480
deadline=$(( $(date +%s) + WAIT_SECONDS ))
say() { printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$*"; }
say "waiting for the rewrite; HEAD $(git rev-parse --short HEAD), local changes: $(git status --porcelain | wc -l)"
while [ "$(date +%s)" -lt "$deadline" ]; do
  if ! git fetch -q origin main 2>/dev/null; then sleep "$CHECK_SECONDS"; continue; fi
  if git merge-base --is-ancestor HEAD origin/main 2>/dev/null; then sleep "$CHECK_SECONDS"; continue; fi
  key="$(git log -1 --format='%at %s' HEAD)"
  match="$(git log --format='%H %at %s' origin/main | while read -r hash rest; do
    if [ "$rest" = "$key" ]; then echo "$hash"; break; fi
  done)"
  if [ -z "$match" ]; then say "main was rewritten but HEAD has no match yet"; sleep "$CHECK_SECONDS"; continue; fi
  if git diff --quiet HEAD "$match"; then same="same files"; else same="files differ: $(git diff --name-only HEAD "$match" | tr '\n' ' ')"; fi
  if git reset -q --keep "$match"; then
    say "moved main to the rewritten $(git rev-parse --short HEAD) (${same})"
    if git pull -q --ff-only; then say "pull --ff-only works again; now at $(git rev-parse --short HEAD)"; fi
    exit 0
  fi
  say "git reset --keep failed (local changes?); nothing changed"
  exit 1
done
say "no rewrite seen within ${WAIT_SECONDS}s; nothing changed"
