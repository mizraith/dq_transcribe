#!/usr/bin/env bash
# Owner OK'd restarting everything (2026-10-16 10:31). Restart the Officials Sign-In server
# (no new tabs) for the Reports entry, then DQ Transcribe (safe stop) for the 12 pt coloured printouts.
SIGNIN_OPEN_TABS=0 bash scripts/start_signin.sh start 2>&1 | tail -4
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
grep -E "whisper-server ready|Traceback" "$HOME/.dq_transcribe/server.log" | head
curl -s -m 5 -o /dev/null -w "DQ page %{http_code}\n" http://127.0.0.1:8000/
curl -s -m 3 -o /dev/null -w "refine 8179: %{http_code}\n" http://127.0.0.1:8179/
curl -s -m 5 -o /dev/null -w "main page %{http_code}\n" http://127.0.0.1:8010/
curl -s -m 5 http://127.0.0.1:8010/desk_shared.js 2>/dev/null | grep -c "dq_event_report" || true
curl -s -m 5 http://127.0.0.1:8010/ | grep -c "dq_event_report" || true
