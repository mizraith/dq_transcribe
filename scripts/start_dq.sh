#!/data/data/com.termux/files/usr/bin/bash
# Start everything for a dq_transcribe session on the tablet, in one command.
#
#   1. Keeps the tablet awake for Termux (termux-wake-lock).
#   2. Updates the code from GitHub (fast-forward only; never overwrites local work).
#   3. Starts the device agent in the background, if it is not already running,
#      so the AI assistant can run commands here.
#   4. (Re)starts the app server, so it always runs the latest code.
#   5. Opens the app in Chrome at http://localhost:8000.
#
# Usage:
#     bash ~/dq_transcribe/scripts/start_dq.sh          # start (or refresh) everything
#     bash ~/dq_transcribe/scripts/start_dq.sh stop     # stop the server and the agent
#     bash ~/dq_transcribe/scripts/start_dq.sh status   # show what is running
#
# To make it a command called dq_transcribe, run this once in Termux:
#     ln -sf ~/dq_transcribe/scripts/start_dq.sh "$PREFIX/bin/dq_transcribe"
# Then just type:  dq_transcribe   (or: dq_transcribe stop / dq_transcribe status)

set -uo pipefail

# --- Settings -----------------------------------------------------------------
REPO_DIRECTORY="$HOME/dq_transcribe"
DATA_DIRECTORY="$HOME/.dq_transcribe"
SERVER_LOG="$DATA_DIRECTORY/server.log"
AGENT_LOG="$DATA_DIRECTORY/agent.log"
APP_URL="http://localhost:8000"
SERVER_PATTERN="python -m dq_transcribe"
AGENT_PATTERN="scripts/device_agent.sh"
SERVER_STARTUP_TIMEOUT_SECONDS=15

COMMAND_START="start"
COMMAND_STOP="stop"
COMMAND_STATUS="status"

# --- Helpers ------------------------------------------------------------------
say() { printf '[dq_transcribe] %s\n' "$*"; }

is_running() { pgrep -f "$1" >/dev/null 2>&1; }

show_status() {
  if is_running "$AGENT_PATTERN"; then say "device agent: running"; else say "device agent: stopped"; fi
  if is_running "$SERVER_PATTERN"; then say "app server:   running ($APP_URL)"; else say "app server:   stopped"; fi
}

stop_all() {
  pkill -f "$SERVER_PATTERN" 2>/dev/null && say "stopped the app server"
  pkill -f "$AGENT_PATTERN" 2>/dev/null && say "stopped the device agent"
  command -v termux-wake-unlock >/dev/null && termux-wake-unlock
  show_status
}

wait_for_server() {
  local waited=0
  until python - "$APP_URL" <<'PYTHON' 2>/dev/null
import sys, urllib.request
urllib.request.urlopen(sys.argv[1], timeout=2)
PYTHON
  do
    sleep 1
    waited=$((waited + 1))
    if [ "$waited" -ge "$SERVER_STARTUP_TIMEOUT_SECONDS" ]; then
      return 1
    fi
  done
}

start_all() {
  mkdir -p "$DATA_DIRECTORY"
  cd "$REPO_DIRECTORY" || { say "cannot find $REPO_DIRECTORY"; exit 1; }

  command -v termux-wake-lock >/dev/null && termux-wake-lock && say "wake lock on"

  if git pull --ff-only -q; then
    say "code up to date ($(git log -1 --format='%h %s'))"
  else
    say "could not update the code (offline?); using what is here"
  fi

  if is_running "$AGENT_PATTERN"; then
    say "device agent already running"
  else
    nohup bash "$REPO_DIRECTORY/$AGENT_PATTERN" >>"$AGENT_LOG" 2>&1 &
    disown
    say "device agent started (log: $AGENT_LOG)"
  fi

  pkill -f "$SERVER_PATTERN" 2>/dev/null && sleep 1
  PYTHONPATH=src nohup python -m dq_transcribe >"$SERVER_LOG" 2>&1 &
  disown
  if wait_for_server; then
    say "app server running at $APP_URL"
  else
    say "app server did not answer; last lines of $SERVER_LOG:"
    tail -20 "$SERVER_LOG"
    exit 1
  fi

  if command -v termux-open-url >/dev/null; then
    termux-open-url "$APP_URL" && say "opened $APP_URL in the browser"
  else
    say "open $APP_URL in Chrome"
  fi
  say "done. Keep Chrome in front with the screen on while capturing."
}

# --- Main ---------------------------------------------------------------------
case "${1:-$COMMAND_START}" in
  "$COMMAND_START") start_all ;;
  "$COMMAND_STOP") stop_all ;;
  "$COMMAND_STATUS") show_status ;;
  *) say "usage: dq_transcribe [$COMMAND_START|$COMMAND_STOP|$COMMAND_STATUS]"; exit 2 ;;
esac
