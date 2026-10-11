#!/usr/bin/env bash
# Queue a script to run on the tablet and wait for its report.
#
# This is the assistant's side of the relay described in device_agent.sh: it
# copies a script into device_tasks/, commits and pushes it to main, then polls
# the device-reports branch until the tablet's agent publishes the output.
#
# Usage (from the repo root):
#     bash scripts/run_on_device.sh path/to/task.sh [wait_seconds]
#
# Environment: COMMIT_TRAILERS (optional text appended to the commit message),
# POLL_INTERVAL_SECONDS (default 5).

set -euo pipefail

DEFAULT_WAIT_SECONDS=300
POLL_INTERVAL_SECONDS="${POLL_INTERVAL_SECONDS:-5}"
TASKS_DIRECTORY_NAME="device_tasks"
TASK_FILE_EXTENSION=".sh"
REPORTS_BRANCH="device-reports"
REPORT_FILE_EXTENSION=".txt"
MAIN_BRANCH="main"
TIMESTAMP_FORMAT="%Y%m%dT%H%M%SZ"
NO_REPORT_EXIT_CODE=2

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ $# -lt 1 ]; then
  echo "Usage: bash scripts/run_on_device.sh path/to/task.sh [wait_seconds]" >&2
  exit 64
fi
task_source="$1"
wait_seconds="${2:-$DEFAULT_WAIT_SECONDS}"

task_name="$(date -u +"$TIMESTAMP_FORMAT")_$(basename "$task_source" "$TASK_FILE_EXTENSION")"
task_relative_path="${TASKS_DIRECTORY_NAME}/${task_name}${TASK_FILE_EXTENSION}"
report_relative_path="${task_name}${REPORT_FILE_EXTENSION}"

mkdir -p "${REPO_ROOT}/${TASKS_DIRECTORY_NAME}"
cp "$task_source" "${REPO_ROOT}/${task_relative_path}"

commit_message="device task: ${task_name}"
if [ -n "${COMMIT_TRAILERS:-}" ]; then
  commit_message="${commit_message}"$'\n\n'"${COMMIT_TRAILERS}"
fi

git -C "$REPO_ROOT" add "$task_relative_path"
git -C "$REPO_ROOT" commit -q -m "$commit_message"
git -C "$REPO_ROOT" pull -q --rebase --autostash origin "$MAIN_BRANCH"
git -C "$REPO_ROOT" push -q origin "$MAIN_BRANCH"
echo "Queued ${task_name}; waiting up to ${wait_seconds}s for the tablet..." >&2

deadline=$(( $(date +%s) + wait_seconds ))
while [ "$(date +%s)" -lt "$deadline" ]; do
  git -C "$REPO_ROOT" fetch -q origin \
    "+${REPORTS_BRANCH}:refs/remotes/origin/${REPORTS_BRANCH}" 2>/dev/null || true
  if git -C "$REPO_ROOT" cat-file -e "origin/${REPORTS_BRANCH}:${report_relative_path}" 2>/dev/null; then
    git -C "$REPO_ROOT" show "origin/${REPORTS_BRANCH}:${report_relative_path}"
    exit 0
  fi
  sleep "$POLL_INTERVAL_SECONDS"
done

echo "No report after ${wait_seconds}s. Is device_agent.sh running on the tablet?" >&2
exit "$NO_REPORT_EXIT_CODE"
