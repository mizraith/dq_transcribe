#!/usr/bin/env bash
# Restart the app so it runs end of meet: archive, close meet, empty trash. No timing test.
pkill -f "python -m dq_transcribe" 2>/dev/null && sleep 2
PYTHONPATH=src nohup python -m dq_transcribe > "$HOME/.dq_transcribe/server.log" 2>&1 &
disown
for i in $(seq 1 30); do
  grep -q "whisper-server ready: ggml-small.en" "$HOME/.dq_transcribe/server.log" && grep -q "whisper-server ready: ggml-base" "$HOME/.dq_transcribe/server.log" && break
  sleep 1
done
git log -1 --format="running %h"
grep -E "whisper-server ready|Error|Traceback" "$HOME/.dq_transcribe/server.log" | head
FIRST_DQ=$(curl -s http://127.0.0.1:8000/api/dqs | python -c "import json,sys;d=json.load(sys.stdin)['dqs'];print(d[0]['id'] if d else 0)")
curl -s -o /dev/null -w "slip page status %{http_code}\n" "http://127.0.0.1:8000/slips?ids=$FIRST_DQ"
curl -s -o /dev/null -w "font status %{http_code}\n" http://127.0.0.1:8000/fonts/dancing-script-latin-600-normal.woff2
curl -s http://127.0.0.1:8000/api/dqs | python -c "import json,sys,collections;d=json.load(sys.stdin)[\"dqs\"];print(len(d),\"DQs\", dict(collections.Counter(x[\"status\"] for x in d)))"
MEET=$(curl -s http://127.0.0.1:8000/api/meets | python -c "import json,sys;print(json.load(sys.stdin)[\"active_meet_id\"] or 0)"); curl -s -o /dev/null -w "archive status %{http_code}, %{size_download} bytes\n" "http://127.0.0.1:8000/api/meets/$MEET/archive"
