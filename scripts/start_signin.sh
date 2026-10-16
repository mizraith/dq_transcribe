#!/usr/bin/env bash
# Start the Officials Sign-In server (which also serves the Admin Assistant main page and
# Coaches Sign-In), in one command.
#
#   1. Keeps the tablet awake (Termux only: termux-wake-lock).
#   2. Updates the code from GitHub (fast-forward only; never overwrites local work).
#   3. (Re)starts the sign-in server, so it always runs the latest code.
#   4. Opens two browser tabs: Officials Sign-In (http://localhost:8010/officials) and
#      Coaches Sign-In (http://localhost:8010/coaches). Both use the same server and data;
#      the Admin Assistant main page (meets, app launcher) is http://localhost:8010/.
#      SIGNIN_OPEN_TABS=0 opens no tabs (start_admin_assistant.sh opens the main page).
#
# It never starts, stops or restarts dq_transcribe, its whisper servers or the
# device agent: the two apps are independent.
#
# Works on Android (Termux), ChromeOS (Linux), macOS and Linux. Needs Python 3
# and Chrome only; card reading (OCR) runs inside Chrome from bundled files.
#
# Usage:
#     bash ~/dq_transcribe/scripts/start_signin.sh          # start (or refresh)
#     bash ~/dq_transcribe/scripts/start_signin.sh stop     # stop the server
#     bash ~/dq_transcribe/scripts/start_signin.sh status   # show whether it runs
#
# To make it a command called officials_signup (Termux shown; on a Mac or Linux
# use any folder on your PATH, such as /usr/local/bin):
#     ln -sf ~/dq_transcribe/scripts/start_signin.sh "$PREFIX/bin/officials_signup"

set -uo pipefail

# --- Settings -----------------------------------------------------------------
REPO_DIRECTORY="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null || echo "${BASH_SOURCE[0]}")")/.." && pwd)"
DATA_DIRECTORY="$HOME/.officials_signin"
SERVER_LOG="$DATA_DIRECTORY/server.log"
APP_URL="http://localhost:8010"
OFFICIALS_URL="$APP_URL/officials"
COACHES_URL="$APP_URL/coaches"
OPEN_TABS="${SIGNIN_OPEN_TABS:-1}"  # 0: start the server only, open no browser tabs
OPEN_TABS_OFF="0"
# Android can drop a second "open this URL" that arrives while Chrome is still busy.
BROWSER_SETTLE_SECONDS=3
SERVER_MODULE="officials_signin"
SERVER_PATTERN="python[0-9.]* -m $SERVER_MODULE"
SERVER_STARTUP_TIMEOUT_SECONDS=30  # generous: whisper servers may be loading models at the same time

COMMAND_START="start"
COMMAND_STOP="stop"
COMMAND_STATUS="status"

# --- Helpers ------------------------------------------------------------------
say() { printf '[officials_signin] %s\n' "$*"; }

python_command() {
  if command -v python3 >/dev/null; then echo python3; else echo python; fi
}

is_running() { pgrep -f "$SERVER_PATTERN" >/dev/null 2>&1; }

show_status() {
  if is_running; then say "server: running ($APP_URL)"; else say "server: stopped"; fi
}

stop_server() {
  pkill -f "$SERVER_PATTERN" 2>/dev/null && say "stopped the sign-in server" && sleep 1
  show_status
}

wait_for_server() {
  local waited=0
  until "$(python_command)" - "$APP_URL" <<'PYTHON' 2>/dev/null
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

# Open one address in a browser tab (Termux, macOS or Linux); fails when none can.
open_browser() {
  local url="$1"
  if command -v termux-open-url >/dev/null; then
    termux-open-url "$url"
  elif [ "$(uname)" = "Darwin" ]; then
    open -a "Google Chrome" "$url" 2>/dev/null || open "$url"
  elif command -v xdg-open >/dev/null; then
    xdg-open "$url" >/dev/null 2>&1
  else
    return 1
  fi
}

start_server() {
  mkdir -p "$DATA_DIRECTORY"
  cd "$REPO_DIRECTORY" || { say "cannot find $REPO_DIRECTORY"; exit 1; }

  command -v termux-wake-lock >/dev/null && termux-wake-lock && say "wake lock on"

  if git pull --ff-only -q; then
    say "code up to date ($(git log -1 --format='%h %s'))"
  else
    say "could not update the code (offline?); using what is here"
  fi

  pkill -f "$SERVER_PATTERN" 2>/dev/null && sleep 1
  # Append (never overwrite) so the log of a failed start survives the next attempt.
  printf '\n=== %s start ===\n' "$(date '+%Y-%m-%d %H:%M:%S')" >>"$SERVER_LOG"
  PYTHONPATH=src nohup "$(python_command)" -m "$SERVER_MODULE" >>"$SERVER_LOG" 2>&1 &
  disown
  if wait_for_server; then
    say "server running at $APP_URL"
  else
    say "server did not answer after ${SERVER_STARTUP_TIMEOUT_SECONDS}s; last lines of $SERVER_LOG:"
    tail -20 "$SERVER_LOG"
    exit 1
  fi

  if [ "$OPEN_TABS" = "$OPEN_TABS_OFF" ]; then
    return 0
  fi
  if open_browser "$OFFICIALS_URL"; then
    say "opened $OFFICIALS_URL"
    sleep "$BROWSER_SETTLE_SECONDS"
    open_browser "$COACHES_URL" && say "opened $COACHES_URL"
  else
    say "open $OFFICIALS_URL and $COACHES_URL in Chrome"
  fi
}

# --- Main ---------------------------------------------------------------------
case "${1:-$COMMAND_START}" in
  "$COMMAND_START") start_server ;;
  "$COMMAND_STOP") stop_server ;;
  "$COMMAND_STATUS") show_status ;;
  *) say "usage: officials_signup [$COMMAND_START|$COMMAND_STOP|$COMMAND_STATUS]"; exit 2 ;;
esac
