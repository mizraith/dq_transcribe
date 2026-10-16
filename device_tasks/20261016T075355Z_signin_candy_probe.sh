#!/usr/bin/env bash
# Officials Sign-In: read-only look at today's Candy Meet in dq_transcribe (name, dates,
# sessions from the loaded Meet Manager file) and at what Officials Sign-In has now.
# Opens dq_transcribe's database read-only; changes nothing anywhere.
set -uo pipefail
python3 - <<'PY'
import json, sqlite3, urllib.request
from pathlib import Path
path = Path.home() / ".dq_transcribe" / "notes.db"
db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
db.row_factory = sqlite3.Row
print("== dq_transcribe meets")
for row in db.execute("SELECT id, name, start_date FROM meets ORDER BY id"):
    print(dict(row))
print("== meet files")
for row in db.execute("SELECT id, meet_id, loaded_at, file_format, meet_name, summary FROM meet_files ORDER BY id"):
    print(dict(row))
print("== program sessions")
for row in db.execute("SELECT file_id, number, name, day, start_time, event_numbers FROM meet_program_sessions ORDER BY file_id, CAST(number AS INTEGER)"):
    item = dict(row)
    events = json.loads(item["event_numbers"] or "[]") if (item["event_numbers"] or "").startswith("[") else item["event_numbers"]
    item["event_numbers"] = f"{len(events)} events" if isinstance(events, list) else events
    print(item)
print("== events per session (from events table)")
for row in db.execute("SELECT file_id, session, COUNT(*) AS n, MIN(CAST(number AS INTEGER)) AS first, MAX(CAST(number AS INTEGER)) AS last FROM meet_program_events GROUP BY file_id, session"):
    print(dict(row))
for name, url in (("signin state", "http://127.0.0.1:8010/api/state"), ("signin meets", "http://127.0.0.1:8010/api/meets")):
    print("==", name)
    try:
        data = json.load(urllib.request.urlopen(url, timeout=5))
        if "signins" in data:
            data["signins"] = f"{len(data['signins'])} sign-ins"
        print(json.dumps(data, indent=1)[:3000])
    except Exception as error:
        print("not reachable:", error)
PY
