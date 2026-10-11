#!/usr/bin/env bash
# End-to-end test of the device relay (device_agent.sh + run_on_device.sh).
#
# Simulates GitHub with a local bare repository, the tablet with one clone that
# runs the agent, and the assistant with a second clone that queues a task.
#
# Usage (from the repo root):
#     bash tests/test_device_relay.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TASK_OUTPUT_MARKER="hello-from-the-tablet"
TASK_EXIT_CODE=3
ASSISTANT_WAIT_SECONDS=60
AGENT_STARTUP_SECONDS=4

scratch="$(mktemp -d)"
agent_pid=""

cleanup() {
  if [ -n "$agent_pid" ]; then
    kill "$agent_pid" 2>/dev/null || true
    wait "$agent_pid" 2>/dev/null || true
  fi
  rm -rf "$scratch"
}
trap cleanup EXIT

configure_identity() {
  git -C "$1" config user.name "test"
  git -C "$1" config user.email "test@localhost"
}

fail() {
  echo "FAIL: $*" >&2
  echo "--- agent log ---" >&2
  cat "${scratch}/agent.log" >&2 || true
  exit 1
}

# Fake GitHub, seeded with the scripts under test.
git init -q --bare -b main "${scratch}/origin.git"
git clone -q "${scratch}/origin.git" "${scratch}/tablet" 2>/dev/null
configure_identity "${scratch}/tablet"
mkdir -p "${scratch}/tablet/scripts"
cp "${REPO_ROOT}/scripts/device_agent.sh" "${REPO_ROOT}/scripts/run_on_device.sh" "${scratch}/tablet/scripts/"
git -C "${scratch}/tablet" add -A
git -C "${scratch}/tablet" commit -q -m "seed"
git -C "${scratch}/tablet" push -q origin main

# The "tablet" starts its agent.
AGENT_STATE_DIRECTORY="${scratch}/agent_state" POLL_INTERVAL_SECONDS=1 \
  bash "${scratch}/tablet/scripts/device_agent.sh" > "${scratch}/agent.log" 2>&1 &
agent_pid=$!
sleep "$AGENT_STARTUP_SECONDS"
kill -0 "$agent_pid" 2>/dev/null || fail "agent exited early"

# The "assistant" queues a task and waits for the report.
git clone -q "${scratch}/origin.git" "${scratch}/assistant" 2>/dev/null
configure_identity "${scratch}/assistant"
printf 'echo %s\npwd\nexit %s\n' "$TASK_OUTPUT_MARKER" "$TASK_EXIT_CODE" > "${scratch}/probe.sh"

report="$(cd "${scratch}/assistant" && POLL_INTERVAL_SECONDS=1 \
  bash scripts/run_on_device.sh "${scratch}/probe.sh" "$ASSISTANT_WAIT_SECONDS")" \
  || fail "no report came back"

echo "$report" | grep -q "$TASK_OUTPUT_MARKER" || fail "report is missing the task output"
echo "$report" | grep -q "exit_code: ${TASK_EXIT_CODE}" || fail "report is missing the exit code"
echo "$report" | grep -q "${scratch}/tablet" || fail "task did not run in the tablet's repo folder"

# The task must have run exactly once (no replay on later polls).
sleep 3
run_count="$(grep -c "Running " "${scratch}/agent.log")"
[ "$run_count" -eq 1 ] || fail "expected exactly 1 task run, saw ${run_count}"

echo "PASS: relay delivered a task and returned its report"
