#!/usr/bin/env bash
# Restart DQ Transcribe to install the event printouts (Report/Summary, status, meta, 14 pt): stop it
# stuck child and leftover whisper servers, start, and check both transcription passes.
# Never touches the Officials Sign-In server.
pkill -f "python -m dq_transcribe" 2>/dev/null
for i in $(seq 1 10); do pgrep -f "python -m dq_transcribe" >/dev/null || break; sleep 1; done
pkill -9 -f "python -m dq_transcribe" 2>/dev/null
pkill -f "whisper-server" 2>/dev/null
sleep 2
PYTHONPATH=src nohup python -m dq_transcribe > "$HOME/.dq_transcribe/server.log" 2>&1 &
disown
for i in $(seq 1 90); do
  grep -q "whisper-server ready: ggml-small.en" "$HOME/.dq_transcribe/server.log" && grep -q "whisper-server ready: ggml-base" "$HOME/.dq_transcribe/server.log" && break
  sleep 1
done
git log -1 --format="running %h"
grep -E "whisper-server|Coach page|Error|Traceback|priority" "$HOME/.dq_transcribe/server.log" | head
ps -ef | grep -E "whisper-server|python -m dq_transcribe" | grep -v grep | cut -c1-70
curl -s -m 5 -o /dev/null -w "DQ page %{http_code}\n" http://127.0.0.1:8000/
curl -s -m 3 -o /dev/null -w "draft 8178: %{http_code}\n" http://127.0.0.1:8178/
curl -s -m 3 -o /dev/null -w "refine 8179: %{http_code}\n" http://127.0.0.1:8179/
curl -s -m 5 -o /dev/null -w "main page %{http_code}\n" http://127.0.0.1:8010/
curl -s -m 8 "http://127.0.0.1:8000/event-summary?all=1&suite_meet_id=current" | grep -o "<title>[^<]*</title>\|<h1>[^<]*</h1>" | head -2
