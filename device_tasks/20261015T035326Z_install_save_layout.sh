#!/usr/bin/env bash
# Restart the app so it runs the latest code (stroke tags on code buttons, Save button layout). No timing test.
pkill -f "python -m dq_transcribe" 2>/dev/null && sleep 2
PYTHONPATH=src nohup python -m dq_transcribe > "$HOME/.dq_transcribe/server.log" 2>&1 &
disown
for i in $(seq 1 30); do
  grep -q "whisper-server ready: ggml-small.en" "$HOME/.dq_transcribe/server.log" && grep -q "whisper-server ready: ggml-base" "$HOME/.dq_transcribe/server.log" && break
  sleep 1
done
git log -1 --format="running %h"
grep -E "Refine pass|whisper-server ready" "$HOME/.dq_transcribe/server.log"
curl -s -o /dev/null -w "page status %{http_code}\n" http://127.0.0.1:8000/
curl -s -o /dev/null -w "meet script status %{http_code}\n" http://127.0.0.1:8000/meet_view.js
curl -s http://127.0.0.1:8000/api/candidates | python -c "import json,sys;print(len(json.load(sys.stdin)[\"candidates\"]), \"detected calls in the active meet\")"
