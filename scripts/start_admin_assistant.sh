#!/usr/bin/env bash
# Start both Swimming Admin Assistant apps in one command. Chrome tabs open in this
# order, left to right (owner, 2026-10-16):
#   1. Officials Sign-In  (scripts/start_signin.sh: server restart, http://localhost:8010)
#   2. Coaches Sign-In    (same server, http://localhost:8010/coaches; follows the
#                          officials tab's meet and session)
#   3. dq_transcribe      (scripts/start_dq.sh: wake lock, update, device agent,
#                          server restart, http://localhost:8000)
#   4. Coaches' DQ view   (dq_transcribe's coach page, http://localhost:8020; it answers
#                          when the coach page is switched on in dq_transcribe)
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
COACH_DQ_VIEW_URL="http://localhost:8020/"

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
    bash "$SIGNIN_SCRIPT" "$command_name"
    signin_exit_code=$?
    # Give Chrome time to finish opening the tabs; Android can drop an "open this
    # URL" request that arrives while Chrome is still busy.
    [ "$command_name" = "$COMMAND_START" ] && sleep "$BROWSER_SETTLE_SECONDS"
    bash "$DQ_SCRIPT" "$command_name"
    dq_exit_code=$?
    if [ "$command_name" = "$COMMAND_START" ]; then
      sleep "$BROWSER_SETTLE_SECONDS"
      open_browser "$COACH_DQ_VIEW_URL" && printf '[admin_assistant] opened %s\n' "$COACH_DQ_VIEW_URL"
    fi
    # Fail if either app failed, so problems are not hidden.
    [ "$dq_exit_code" -eq 0 ] && [ "$signin_exit_code" -eq 0 ]
    ;;
  *)
    printf '[admin_assistant] usage: admin_assistant [%s|%s|%s]\n' "$COMMAND_START" "$COMMAND_STOP" "$COMMAND_STATUS"
    exit 2
    ;;
esac
