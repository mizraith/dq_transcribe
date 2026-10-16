#!/usr/bin/env bash
# Restart the app so New meet accepts Meet Manager files; list the meets (read-only). No timing test.
pkill -f "python -m dq_transcribe" 2>/dev/null && sleep 2
PYTHONPATH=src nohup python -m dq_transcribe > "$HOME/.dq_transcribe/server.log" 2>&1 &
disown
for i in $(seq 1 30); do
  grep -q "whisper-server ready: ggml-small.en" "$HOME/.dq_transcribe/server.log" && grep -q "whisper-server ready: ggml-base" "$HOME/.dq_transcribe/server.log" && break
  sleep 1
done
git log -1 --format="running %h"
grep -E "whisper-server ready|Error|Traceback" "$HOME/.dq_transcribe/server.log" | head
curl -s -o /dev/null -w "page status %{http_code}\n" http://127.0.0.1:8000/
curl -s http://127.0.0.1:8000/api/meets | python -c "import json,sys;d=json.load(sys.stdin);[print(m[\"id\"], m[\"name\"], m[\"start_date\"], m[\"clip_count\"], \"clips\", \"ACTIVE\" if m[\"id\"]==d[\"active_meet_id\"] else \"\") for m in d[\"meets\"]]"
