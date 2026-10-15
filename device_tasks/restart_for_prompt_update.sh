#!/usr/bin/env bash
# Restart the app server so it loads the updated whisper word list ("Confirmed").
pkill -f "python -m dq_transcribe" 2>/dev/null && sleep 1
PYTHONPATH=src nohup python -m dq_transcribe > "$HOME/.dq_transcribe/server.log" 2>&1 &
disown
sleep 3
git log -1 --format="running %h"
grep -i "refine pass" "$HOME/.dq_transcribe/server.log"
curl -s -o /dev/null -w "page status %{http_code}\n" http://127.0.0.1:8000/
