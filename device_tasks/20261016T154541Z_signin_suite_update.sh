#!/usr/bin/env bash
# Officials Sign-In: move the tablet to the Admin Assistant main page (owner's OK,
# 2026-10-16 08:45). The device agent's pull brings the new code; the sign-in server
# restarts itself on code changes. This task waits for it, checks the new pages, adds
# DQ Transcribe's "10/14 Test" meet to the meets list (owner's choice), and keeps the
# Candy Meet, Friday PM, as the current meet and session. Never touches dq_transcribe.
set -uo pipefail
echo "code: $(git log -1 --format='%h %s')"
python3 - <<'PY'
import json, time, urllib.request
BASE = "http://127.0.0.1:8010"
CANDY_MEET = "All Treats No Tricks Candy Meet Block Party"
TEST_MEET = "10/14 Test"
def get(path):
    return urllib.request.urlopen(BASE + path, timeout=10)
def get_json(path):
    return json.load(get(path))
def post(path, body):
    request = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(request, timeout=10))
# Wait for the restarted server to serve the new main page.
for attempt in range(60):
    try:
        if b"app-launcher" in get("/").read():
            print("main page ready after", attempt, "s")
            break
    except Exception:
        pass
    time.sleep(1)
else:
    print("main page NOT ready after 60 s")
for path in ("/officials", "/coaches", "/home.js", "/meets.js", "/roster.json"):
    print(path, get(path).status)
meets = get_json("/api/suite/meets")["meets"]
candy = [meet for meet in meets if meet["name"] == CANDY_MEET]
if not [meet for meet in meets if meet["name"] == TEST_MEET]:
    reply = post("/api/meets/save", {
        "id": None, "name": TEST_MEET, "start_date": "2026-10-14",
        "sessions": [{"id": None, "name": "Wednesday", "date": "2026-10-14", "start_time": None,
                      "session_type": None, "officials_meeting_time": None, "estimated_minutes": None}],
    })
    print("added", TEST_MEET, "id", reply.get("id"))
else:
    print(TEST_MEET, "already there")
# Saving a meet opens it: put the Candy Meet, Friday PM, back.
if candy:
    post("/api/suite/select", {"meet_id": candy[0]["id"]})
    current = get_json("/api/suite/current")
    friday = [s for s in current["sessions"] if s["name"] == "Friday PM"]
    if friday:
        current = post("/api/suite/select", {"session_id": friday[0]["id"]})
    print("current:", current["meet"], "| session:", [s["name"] for s in current["sessions"] if s["id"] == current["active_session_id"]])
for meet in get_json("/api/suite/meets")["meets"]:
    print("meet:", meet["name"], meet["start_date"], "sessions", meet["session_count"], "signed in", meet["signin_count"], "archived" if meet["archived"] else "")
PY
