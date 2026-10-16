#!/usr/bin/env bash
# Restart the app to install the coach page sort (by event / by swimmer); report the coach page state.
pkill -f "python -m dq_transcribe" 2>/dev/null && sleep 2
PYTHONPATH=src nohup python -m dq_transcribe > "$HOME/.dq_transcribe/server.log" 2>&1 &
disown
for i in $(seq 1 40); do
  grep -q "whisper-server ready: ggml-small.en" "$HOME/.dq_transcribe/server.log" && grep -q "whisper-server ready: ggml-base" "$HOME/.dq_transcribe/server.log" && break
  sleep 1
done
git log -1 --format="running %h"
grep -E "whisper-server ready|Coach page|Error|Traceback" "$HOME/.dq_transcribe/server.log" | head
curl -s -o /dev/null -w "admin page %{http_code}\n" http://127.0.0.1:8000/
curl -s http://127.0.0.1:8000/api/coach-page | python -c "import json,sys;s=json.load(sys.stdin)['coach_page'];print('coach page running', s['running'], s['urls'])"
