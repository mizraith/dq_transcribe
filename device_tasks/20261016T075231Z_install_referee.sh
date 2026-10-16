#!/usr/bin/env bash
# Restart the app to install: referee-made calls need no other referee; chief judge optional. Rebuild DEMO MEET (only that meet).
pkill -f "python -m dq_transcribe" 2>/dev/null && sleep 2
PYTHONPATH=src nohup python -m dq_transcribe > "$HOME/.dq_transcribe/server.log" 2>&1 &
disown
for i in $(seq 1 40); do
  grep -q "whisper-server ready: ggml-small.en" "$HOME/.dq_transcribe/server.log" && grep -q "whisper-server ready: ggml-base" "$HOME/.dq_transcribe/server.log" && break
  sleep 1
done
curl -s -X POST -H "Content-Type: application/json" -d "{}" http://127.0.0.1:8000/api/training-meet/rebuild; echo
git log -1 --format="running %h"
grep -E "whisper-server ready|Coach page|Training meet|Automatic DQs|Error|Traceback" "$HOME/.dq_transcribe/server.log" | head
curl -s -o /dev/null -w "admin page %{http_code}\n" http://127.0.0.1:8000/
curl -s http://127.0.0.1:8000/api/auto-dqs; echo
curl -s http://127.0.0.1:8000/api/meets | python -c "import json,sys;d=json.load(sys.stdin);[print(m['id'], m['name'], m['start_date'], m['clip_count'], 'clips', 'ACTIVE' if m['id']==d['active_meet_id'] else '') for m in d['meets']]"
