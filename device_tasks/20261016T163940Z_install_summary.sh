#!/usr/bin/env bash
# Install the event DQ summary for the Reports: restart only DQ (never the Officials Sign-In server).
# Safety: skip the restart if a clip arrived in the last 3 minutes (capturing may be on).
RECENT=$(python - <<'PY'
import sqlite3, os, datetime
db = sqlite3.connect(os.path.expanduser("~/.dq_transcribe/notes.db"))
row = db.execute("SELECT MAX(created_at) FROM clips").fetchone()[0]
if row:
    age = (datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromisoformat(row)).total_seconds()
    print("recent" if age < 180 else "idle")
else:
    print("idle")
PY
)
echo "capture activity: $RECENT"
if [ "$RECENT" = "recent" ]; then echo "NOT restarting: a clip arrived in the last 3 minutes"; exit 0; fi
pkill -f "python -m dq_transcribe" 2>/dev/null && sleep 2
PYTHONPATH=src nohup python -m dq_transcribe > "$HOME/.dq_transcribe/server.log" 2>&1 &
disown
for i in $(seq 1 40); do
  grep -q "whisper-server ready: ggml-small.en" "$HOME/.dq_transcribe/server.log" && grep -q "whisper-server ready: ggml-base" "$HOME/.dq_transcribe/server.log" && break
  sleep 1
done
git log -1 --format="running %h"
grep -E "whisper-server ready|Error|Traceback" "$HOME/.dq_transcribe/server.log" | head
curl -s -o /dev/null -w "DQ page %{http_code}\n" http://127.0.0.1:8000/
SUITE_MEET=$(curl -s http://127.0.0.1:8010/api/suite/current | python -c "import json,sys;d=json.load(sys.stdin);print(d['meet']['id'] if d['meet'] else '')")
echo "suite meet id: $SUITE_MEET"
curl -s -o /dev/null -w "event picker (all statuses) %{http_code}\n" "http://127.0.0.1:8000/event-summary?all=1&suite_meet_id=$SUITE_MEET"
