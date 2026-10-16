#!/usr/bin/env bash
# Restart the app (view tabs, compact left column) and create the workflow demo meet
# ("Workflow demo (test data)": a separate meet; the active meet is not changed). No timing test.
pkill -f "python -m dq_transcribe" 2>/dev/null && sleep 2
PYTHONPATH=src nohup python -m dq_transcribe > "$HOME/.dq_transcribe/server.log" 2>&1 &
disown
for i in $(seq 1 30); do
  grep -q "whisper-server ready: ggml-small.en" "$HOME/.dq_transcribe/server.log" && grep -q "whisper-server ready: ggml-base" "$HOME/.dq_transcribe/server.log" && break
  sleep 1
done
git log -1 --format="running %h"
grep -E "whisper-server ready|Error|Traceback" "$HOME/.dq_transcribe/server.log" | head
PYTHONPATH=src python -m dq_transcribe.demo_data --replace
curl -s http://127.0.0.1:8000/api/meets | python -c "import json,sys;d=json.load(sys.stdin);print('active meet:', [m['name'] for m in d['meets'] if m['id']==d['active_meet_id']], '| meets:', [m['name'] for m in d['meets']])"
