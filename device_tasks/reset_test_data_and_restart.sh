#!/usr/bin/env bash
# Remove the sample clips from the end-to-end test (database and recordings
# under ~/.dq_transcribe only) and restart the server fresh.

DATA_DIRECTORY="$HOME/.dq_transcribe"
SERVER_PATTERN="python -m dq_transcribe"
SERVER_LOG="$DATA_DIRECTORY/server.log"
STARTUP_WAIT_SECONDS=3

pkill -f "$SERVER_PATTERN" 2>/dev/null && sleep 1
rm -f "$DATA_DIRECTORY"/notes.db "$DATA_DIRECTORY"/notes.db-wal "$DATA_DIRECTORY"/notes.db-shm
rm -rf "$DATA_DIRECTORY/recordings"
ls "$DATA_DIRECTORY"
PYTHONPATH=src nohup python -m dq_transcribe > "$SERVER_LOG" 2>&1 &
disown
sleep "$STARTUP_WAIT_SECONDS"
tail -5 "$SERVER_LOG"
