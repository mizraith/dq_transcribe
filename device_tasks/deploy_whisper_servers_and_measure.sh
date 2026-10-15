#!/usr/bin/env bash
# Restart the app with persistent whisper-server processes, wait for the models
# to load, then time temporary copies of clips 4-6 (deleted afterwards).
pkill -f "python -m dq_transcribe" 2>/dev/null && sleep 2
PYTHONPATH=src nohup python -m dq_transcribe > "$HOME/.dq_transcribe/server.log" 2>&1 &
disown
for i in $(seq 1 40); do
  grep -q "whisper-server ready: ggml-small.en" "$HOME/.dq_transcribe/server.log" && grep -q "whisper-server ready: ggml-base" "$HOME/.dq_transcribe/server.log" && break
  sleep 1
done
grep -E "Refine pass|whisper-server|not found" "$HOME/.dq_transcribe/server.log"
pgrep -af whisper-server | cut -c1-120
bash device_tasks/measure_two_pass_with_copies.sh 2>&1 | grep -v "^clips in"
