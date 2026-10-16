#!/usr/bin/env bash
# Start both Swimming Admin Assistant apps in one command:
#   1. dq_transcribe   (scripts/start_dq.sh: wake lock, update, device agent,
#                       server restart, opens http://localhost:8000)
#   2. Officials Sign-In (scripts/start_signin.sh: server restart, opens
#                       http://localhost:8010)
# Each app gets its own Chrome tab.
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

COMMAND_START="start"
COMMAND_STOP="stop"
COMMAND_STATUS="status"

command_name="${1:-$COMMAND_START}"
case "$command_name" in
  "$COMMAND_START"|"$COMMAND_STOP"|"$COMMAND_STATUS")
    bash "$DQ_SCRIPT" "$command_name"
    dq_exit_code=$?
    # Give Chrome time to finish opening the first tab; Android can drop a
    # second "open this URL" request that arrives while Chrome is still starting.
    [ "$command_name" = "$COMMAND_START" ] && sleep "$BROWSER_SETTLE_SECONDS"
    bash "$SIGNIN_SCRIPT" "$command_name"
    signin_exit_code=$?
    # Fail if either app failed, so problems are not hidden.
    [ "$dq_exit_code" -eq 0 ] && [ "$signin_exit_code" -eq 0 ]
    ;;
  *)
    printf '[admin_assistant] usage: admin_assistant [%s|%s|%s]\n' "$COMMAND_START" "$COMMAND_STOP" "$COMMAND_STATUS"
    exit 2
    ;;
esac
