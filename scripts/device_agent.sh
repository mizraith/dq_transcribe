#!/usr/bin/env bash
# Device agent for dq_transcribe.
#
# Runs on the tablet (in Termux) so an AI assistant can run commands there
# without anyone copying and pasting. The assistant cannot connect to the
# tablet, so GitHub is the go-between:
#
#   1. The assistant commits a shell script into device_tasks/ on main.
#   2. This agent notices it (it polls with `git pull`), runs it inside the repo
#      folder, and writes the output to a report file.
#   3. The agent pushes the report to the device-reports branch, where the
#      assistant reads it.
#
# SAFETY: this agent runs whatever scripts appear in device_tasks/ on main. That
# is only safe while the repository is private and only you can push to it. Read
# device_tasks/ any time to see exactly what has run. Press Ctrl+C to stop.
#
# Usage (from anywhere, inside Termux):
#     bash ~/dq_transcribe/scripts/device_agent.sh
#
# Options:
#     --run-existing   Also run tasks already in device_tasks/ the first time the
#                      agent starts. By default those are skipped.
#
# Environment overrides (mostly for testing): POLL_INTERVAL_SECONDS,
# TASK_TIMEOUT_SECONDS, MAX_REPORT_BYTES, AGENT_STATE_DIRECTORY.
#
# Written and tested on Linux; Termux-specific parts are guarded and unverified.

# No `set -e`: the loop must survive a failing task or a flaky network.
set -uo pipefail

POLL_INTERVAL_SECONDS="${POLL_INTERVAL_SECONDS:-15}"
TASK_TIMEOUT_SECONDS="${TASK_TIMEOUT_SECONDS:-600}"
MAX_REPORT_BYTES="${MAX_REPORT_BYTES:-200000}"

TASKS_DIRECTORY_NAME="device_tasks"
TASK_FILE_PATTERN="*.sh"
TASK_FILE_EXTENSION=".sh"
REPORTS_BRANCH="device-reports"
REPORT_FILE_EXTENSION=".txt"
RUN_EXISTING_FLAG="--run-existing"
TIMEOUT_EXIT_CODE=124

AGENT_STATE_DIRECTORY="${AGENT_STATE_DIRECTORY:-${HOME}/.dq_transcribe_agent}"
COMPLETED_TASKS_FILE="${AGENT_STATE_DIRECTORY}/completed_tasks.txt"
REPORTS_CLONE_DIRECTORY="${AGENT_STATE_DIRECTORY}/reports_clone"
REPORTS_GIT_USER_NAME="dq_transcribe device agent"
REPORTS_GIT_USER_EMAIL="device-agent@localhost"

WORK_REPO_DIRECTORY="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TASKS_DIRECTORY="${WORK_REPO_DIRECTORY}/${TASKS_DIRECTORY_NAME}"

log() {
  printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$*"
}

reports_git() {
  git -C "$REPORTS_CLONE_DIRECTORY" "$@"
}

# Create (or refresh) the private clone that holds only the reports branch.
setup_reports_clone() {
  local remote_url
  remote_url="$(git -C "$WORK_REPO_DIRECTORY" remote get-url origin)" || return 1
  mkdir -p "$AGENT_STATE_DIRECTORY"

  if [ ! -d "${REPORTS_CLONE_DIRECTORY}/.git" ]; then
    git init -q -b "$REPORTS_BRANCH" "$REPORTS_CLONE_DIRECTORY" || return 1
    reports_git remote add origin "$remote_url" || return 1
    reports_git config user.name "$REPORTS_GIT_USER_NAME"
    reports_git config user.email "$REPORTS_GIT_USER_EMAIL"
  fi

  if git ls-remote --exit-code --heads "$remote_url" "$REPORTS_BRANCH" >/dev/null 2>&1; then
    reports_git fetch -q origin "$REPORTS_BRANCH" || return 1
    reports_git checkout -q -B "$REPORTS_BRANCH" FETCH_HEAD || return 1
  elif ! reports_git rev-parse --verify -q HEAD >/dev/null; then
    printf 'Reports written by scripts/device_agent.sh, one file per task.\n' \
      > "${REPORTS_CLONE_DIRECTORY}/README.md"
    reports_git add README.md
    reports_git commit -q -m "Initialize device reports branch" || return 1
    reports_git push -q -u origin "$REPORTS_BRANCH" || return 1
  fi
}

# Push committed reports, rebasing once if the remote moved.
publish_reports() {
  if reports_git push -q origin "$REPORTS_BRANCH" 2>/dev/null; then
    return 0
  fi
  reports_git pull -q --rebase origin "$REPORTS_BRANCH" 2>/dev/null
  reports_git push -q origin "$REPORTS_BRANCH"
}

list_task_paths() {
  find "$TASKS_DIRECTORY" -maxdepth 1 -type f -name "$TASK_FILE_PATTERN" 2>/dev/null | sort
}

# Remember the tasks that already exist so a fresh agent does not replay history.
record_existing_tasks_as_completed() {
  local task_path
  : > "$COMPLETED_TASKS_FILE"
  while IFS= read -r task_path; do
    basename "$task_path" >> "$COMPLETED_TASKS_FILE"
  done < <(list_task_paths)
}

is_completed() {
  grep -qxF "$1" "$COMPLETED_TASKS_FILE"
}

# Run one task script from the repo root and write its report file.
run_task() {
  local task_path="$1"
  local task_file task_name report_path output_file started_at exit_code output_size
  task_file="$(basename "$task_path")"
  task_name="$(basename "$task_path" "$TASK_FILE_EXTENSION")"
  report_path="${REPORTS_CLONE_DIRECTORY}/${task_name}${REPORT_FILE_EXTENSION}"
  output_file="$(mktemp)"
  started_at="$(date -Is)"

  (cd "$WORK_REPO_DIRECTORY" && timeout "$TASK_TIMEOUT_SECONDS" bash "$task_path") \
    < /dev/null > "$output_file" 2>&1
  exit_code=$?
  output_size="$(wc -c < "$output_file")"

  {
    echo "task: ${task_name}"
    echo "started: ${started_at}"
    echo "finished: $(date -Is)"
    echo "work_repo_commit: $(git -C "$WORK_REPO_DIRECTORY" rev-parse --short HEAD)"
    echo "exit_code: ${exit_code}"
    if [ "$exit_code" -eq "$TIMEOUT_EXIT_CODE" ]; then
      echo "note: timed out after ${TASK_TIMEOUT_SECONDS} seconds"
    fi
    echo "--- output ---"
    head -c "$MAX_REPORT_BYTES" "$output_file"
    if [ "$output_size" -gt "$MAX_REPORT_BYTES" ]; then
      printf '\n[output truncated at %s bytes]\n' "$MAX_REPORT_BYTES"
    fi
  } > "$report_path"
  rm -f "$output_file"

  echo "$task_file" >> "$COMPLETED_TASKS_FILE"
  reports_git add "$(basename "$report_path")"
  reports_git commit -q -m "report: ${task_name}"
  if publish_reports; then
    log "Finished ${task_name} (exit ${exit_code}); report published."
  else
    log "Finished ${task_name} (exit ${exit_code}); report saved but NOT pushed yet."
  fi
}

cleanup() {
  if command -v termux-wake-unlock >/dev/null 2>&1; then
    termux-wake-unlock
  fi
  log "Agent stopped."
}

main() {
  local run_existing=false
  if [ "${1:-}" = "$RUN_EXISTING_FLAG" ]; then
    run_existing=true
  fi

  mkdir -p "$AGENT_STATE_DIRECTORY"
  if ! setup_reports_clone; then
    log "Could not set up the reports branch. Check your GitHub login (gh auth status)."
    exit 1
  fi
  if [ ! -f "$COMPLETED_TASKS_FILE" ]; then
    if [ "$run_existing" = true ]; then
      : > "$COMPLETED_TASKS_FILE"
    else
      record_existing_tasks_as_completed
    fi
  fi

  trap 'exit 0' INT TERM
  trap cleanup EXIT
  if command -v termux-wake-lock >/dev/null 2>&1; then
    termux-wake-lock
  fi

  log "Agent running in ${WORK_REPO_DIRECTORY}. Checking every ${POLL_INTERVAL_SECONDS}s. Ctrl+C to stop."
  local task_path task_file
  while true; do
    if git -C "$WORK_REPO_DIRECTORY" pull -q --ff-only; then
      while IFS= read -r task_path; do
        task_file="$(basename "$task_path")"
        if ! is_completed "$task_file"; then
          log "Running ${task_file}"
          run_task "$task_path"
        fi
      done < <(list_task_paths)
    else
      log "git pull failed (network or local changes?); will retry."
    fi
    sleep "$POLL_INTERVAL_SECONDS"
  done
}

main "$@"
