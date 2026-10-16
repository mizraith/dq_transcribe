#!/usr/bin/env bash
# Officials Sign-In: set up today's Candy Meet (owner's request, 2026-10-16), from the
# meet loaded into dq_transcribe: one session, Friday 4:45 PM, officials meeting 3:45 PM,
# about 3 hours (26 events, 78 heats). Uses the app's own "save meet" API on this tablet,
# which also makes it the open meet. Skips if a meet with this name already exists.
set -uo pipefail
python3 - <<'PY'
import json, urllib.request
BASE = "http://127.0.0.1:8010"
MEET_NAME = "All Treats No Tricks Candy Meet Block Party"
def get(path):
    return json.load(urllib.request.urlopen(BASE + path, timeout=10))
def post(path, body):
    request = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(request, timeout=10))
existing = [meet for meet in get("/api/meets")["meets"] if meet["name"] == MEET_NAME]
if existing:
    print("already there:", existing[0])
else:
    reply = post("/api/meets/save", {
        "id": None, "name": MEET_NAME, "start_date": "2026-10-16",
        "sessions": [{
            "id": None, "name": "Friday PM", "date": "2026-10-16", "start_time": "16:45", "session_type": "PM",
            "officials_meeting_time": "15:45", "estimated_minutes": 180,
        }],
    })
    print("created meet id", reply.get("id"))
state = get("/api/state")
print("open meet:", state["meet"])
for session in state["sessions"]:
    print("session:", {key: session[key] for key in ("id", "name", "date", "start_time", "session_type", "officials_meeting_time", "estimated_minutes")})
print("active session:", state["active_session_id"])
PY
