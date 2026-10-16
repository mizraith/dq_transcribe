#!/usr/bin/env bash
# Restart the app so it runs "New meet from a meet sheet". Then a read-only check that the
# owner's linked Google Doc meet sheet can be read from the tablet (no meet is created).
pkill -f "python -m dq_transcribe" 2>/dev/null && sleep 2
PYTHONPATH=src nohup python -m dq_transcribe > "$HOME/.dq_transcribe/server.log" 2>&1 &
disown
for i in $(seq 1 30); do
  grep -q "whisper-server ready: ggml-small.en" "$HOME/.dq_transcribe/server.log" && grep -q "whisper-server ready: ggml-base" "$HOME/.dq_transcribe/server.log" && break
  sleep 1
done
git log -1 --format="running %h"
grep -E "whisper-server ready|Error|Traceback" "$HOME/.dq_transcribe/server.log" | head
PYTHONPATH=src python - <<'PYTHON'
import json, urllib.request
from dq_transcribe.meet_files.meet_sheet import download_address, read_meet_sheet_text
url = download_address("https://docs.google.com/document/u/0/d/17CBowgz7Rx7F36UlSDfgxuxaPI6icw-_nzttjKDrscc/mobilebasic")
raw = urllib.request.urlopen(url, timeout=30).read()
print("downloaded", len(raw), "bytes; public:", b"accounts.google.com" not in raw[:20000])
summary = read_meet_sheet_text(raw.decode("utf-8-sig")).summary()
summary["officials"] = len(summary["officials"])
print(json.dumps(summary))
PYTHON
