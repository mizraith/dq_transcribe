#!/usr/bin/env bash
# Recover DQ Transcribe: the old server hung while shutting down and kept port 8000.
# Force-stop only DQ's processes (never the Officials Sign-In server), then start it again.
pkill -9 -f "python -m dq_transcribe" 2>/dev/null
pkill -f "whisper-server" 2>/dev/null
sleep 2
ps -ef | grep -E "dq_transcribe|whisper-server" | grep -v -E "grep|device_tasks" | cut -c1-120
PYTHONPATH=src nohup python -m dq_transcribe > "$HOME/.dq_transcribe/server.log" 2>&1 &
disown
for i in $(seq 1 60); do
  grep -q "whisper-server ready: ggml-small.en" "$HOME/.dq_transcribe/server.log" && grep -q "whisper-server ready: ggml-base" "$HOME/.dq_transcribe/server.log" && break
  sleep 1
done
git log -1 --format="running %h"
grep -E "whisper-server ready|Coach page|Error|Traceback" "$HOME/.dq_transcribe/server.log" | head
curl -s -m 5 -o /dev/null -w "DQ page %{http_code}\n" http://127.0.0.1:8000/
curl -s -m 5 -o /dev/null -w "event picker %{http_code}\n" "http://127.0.0.1:8000/event-summary?all=1&suite_meet_id=3"
curl -s -m 5 -o /dev/null -w "main page %{http_code}\n" http://127.0.0.1:8010/
