#!/usr/bin/env bash
# Start Admin Assistant: both servers, then its main page (owner, 2026-10-16).
#   - Officials Sign-In server (scripts/start_signin.sh, no tabs): serves the Admin
#     Assistant main page (http://localhost:8010/: meets, sessions, app launcher), Officials
#     Sign-In (/officials) and Coaches Sign-In (/coaches).
#   - DQ Transcribe (scripts/start_dq.sh: wake lock, update, device agent, server restart,
#     http://localhost:8000). DQ_OPEN_BROWSER=0 asks it not to open its own tab (once DQ
#     Transcribe supports that; until then it opens its tab as before).
#   - Then opens the main page; the other apps open from its launcher, each in its own tab.
#
# Careful during a meet: "start" RESTARTS the dq_transcribe server (that is what
# start_dq.sh does). Do not run it while capture is recording.
#
# Usage:
#     bash ~/dq_transcribe/scripts/start_admin_assistant.sh          # start both
#     bash ~/dq_transcribe/scripts/start_admin_assistant.sh stop     # stop both (and the device agent)
#     bash ~/dq_transcribe/scripts/start_admin_assistant.sh status   # show both
#
# To make it a command called admin_assistant, run this once in Termux:
#     ln -sf ~/dq_transcribe/scripts/start_admin_assistant.sh "$PREFIX/bin/admin_assistant"

set -uo pipefail

SCRIPTS_DIRECTORY="$(dirname "$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null || echo "${BASH_SOURCE[0]}")")"
DQ_SCRIPT="$SCRIPTS_DIRECTORY/start_dq.sh"
SIGNIN_SCRIPT="$SCRIPTS_DIRECTORY/start_signin.sh"

BROWSER_SETTLE_SECONDS=3
MAIN_PAGE_URL="http://localhost:8010/"

COMMAND_START="start"
COMMAND_STOP="stop"
COMMAND_STATUS="status"

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

command_name="${1:-$COMMAND_START}"
case "$command_name" in
  "$COMMAND_START"|"$COMMAND_STOP"|"$COMMAND_STATUS")
    SIGNIN_OPEN_TABS=0 bash "$SIGNIN_SCRIPT" "$command_name"
    signin_exit_code=$?
    DQ_OPEN_BROWSER=0 bash "$DQ_SCRIPT" "$command_name"
    dq_exit_code=$?
    if [ "$command_name" = "$COMMAND_START" ]; then
      # Give Chrome time to finish any tab DQ Transcribe opened; Android can drop an
      # "open this URL" request that arrives while Chrome is still busy.
      sleep "$BROWSER_SETTLE_SECONDS"
      if open_browser "$MAIN_PAGE_URL"; then
        printf '[admin_assistant] opened %s\n' "$MAIN_PAGE_URL"
      else
        printf '[admin_assistant] open %s in Chrome\n' "$MAIN_PAGE_URL"
      fi
    fi
    # Fail if either app failed, so problems are not hidden.
    [ "$dq_exit_code" -eq 0 ] && [ "$signin_exit_code" -eq 0 ]
    ;;
  *)
    printf '[admin_assistant] usage: admin_assistant [%s|%s|%s]\n' "$COMMAND_START" "$COMMAND_STOP" "$COMMAND_STATUS"
    exit 2
    ;;
esac
