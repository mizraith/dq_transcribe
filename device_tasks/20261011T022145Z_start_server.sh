#!/usr/bin/env bash
# Start the dq_transcribe server in the background and confirm it answers.

SERVER_LOG="$HOME/.dq_transcribe/server.log"
SERVER_PATTERN="python -m dq_transcribe"
SERVER_URL="http://127.0.0.1:8000/"
STARTUP_WAIT_SECONDS=3

mkdir -p "$HOME/.dq_transcribe"

# Replace any server left over from an earlier run.
pkill -f "$SERVER_PATTERN" 2>/dev/null && echo "stopped an older server" && sleep 1

PYTHONPATH=src nohup python -m dq_transcribe > "$SERVER_LOG" 2>&1 &
disown
sleep "$STARTUP_WAIT_SECONDS"

python - <<'PYTHON'
import urllib.request
with urllib.request.urlopen("http://127.0.0.1:8000/", timeout=5) as response:
    page = response.read().decode("utf-8")
print("server answered with status", response.status, "and", len(page), "bytes of HTML")
PYTHON

echo "--- server log ---"
cat "$SERVER_LOG"
