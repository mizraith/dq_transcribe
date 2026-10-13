#!/usr/bin/env bash
# Restart the app server so it runs the new code (trash bin, audio input picker).
SERVER_PATTERN="python -m dq_transcribe"
pkill -f "$SERVER_PATTERN" 2>/dev/null && sleep 1
PYTHONPATH=src nohup python -m dq_transcribe > "$HOME/.dq_transcribe/server.log" 2>&1 &
disown
sleep 3
git log -1 --format="running %h %s"
curl -s "http://127.0.0.1:8000/api/clips?view=trash" | head -c 200; echo
tail -3 "$HOME/.dq_transcribe/server.log"
