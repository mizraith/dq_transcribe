#!/usr/bin/env bash
# Restart the app with meet setup, then create the "10/14 Test" meet (Oct 14) and
# file clips 25-52 under it. No timing test.
pkill -f "python -m dq_transcribe" 2>/dev/null && sleep 2
PYTHONPATH=src nohup python -m dq_transcribe > "$HOME/.dq_transcribe/server.log" 2>&1 &
disown
for i in $(seq 1 30); do
  grep -q "whisper-server ready: ggml-small.en" "$HOME/.dq_transcribe/server.log" && grep -q "whisper-server ready: ggml-base" "$HOME/.dq_transcribe/server.log" && break
  sleep 1
done
git log -1 --format="running %h"
grep -E "Refine pass|whisper-server ready" "$HOME/.dq_transcribe/server.log"
python - <<'PYTHON'
import json, urllib.request
BASE = "http://127.0.0.1:8000/api/meets"
def post(url, payload):
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(request))
meets = json.load(urllib.request.urlopen(BASE))["meets"]
existing = [m for m in meets if m["name"] == "10/14 Test"]
meet_id = existing[0]["id"] if existing else post(BASE, {"name": "10/14 Test", "start_date": "2026-10-14"})["meet_id"]
print("meet id", meet_id, post(f"{BASE}/{meet_id}/assign", {"clip_ids": list(range(25, 53))}))
urllib.request.urlopen(urllib.request.Request(f"{BASE}/{meet_id}/activate", data=b"x"))
print(json.load(urllib.request.urlopen(BASE)))
PYTHON
