#!/usr/bin/env bash
# Restart the server with two-pass transcription, reprocess real clips 4-6, and
# report draft vs refined text and timings (the passes overlap in time).
pkill -f "python -m dq_transcribe" 2>/dev/null && sleep 1
PYTHONPATH=src nohup python -m dq_transcribe > "$HOME/.dq_transcribe/server.log" 2>&1 &
disown
sleep 3
grep -i "refine pass" "$HOME/.dq_transcribe/server.log"
python - <<'PYTHON'
import json, time, urllib.request
BASE = "http://127.0.0.1:8000/api/clips"
ids = [4, 5, 6]
start = time.time()
for clip_id in ids:
    urllib.request.urlopen(urllib.request.Request(f"{BASE}/{clip_id}/reprocess", data=b"x", method="POST")).read()
seen_draft = {}
while time.time() - start < 240:
    clips = {c["id"]: c for c in json.load(urllib.request.urlopen(BASE))["clips"] if c["id"] in ids}
    for clip_id, clip in clips.items():
        if clip["status"] == "done" and clip_id not in seen_draft:
            seen_draft[clip_id] = round(time.time() - start, 1)
    if all(c["status"] == "done" and c["refine_status"] in ("done", "failed", "skipped") for c in clips.values()):
        break
    time.sleep(1)
print(f"all finished after {time.time() - start:.1f} s")
for clip_id in ids:
    c = clips[clip_id]
    print(f"clip {clip_id}: {c['duration_seconds']:.1f} s audio | draft ready at {seen_draft.get(clip_id)} s "
          f"(draft {c['transcribe_seconds']:.1f} s) | refine {c['refine_status']} {c['refine_seconds'] or 0:.1f} s")
    for u in c["utterances"]:
        print(f"   draft:   {u['original_text']}")
        print(f"   refined: {u['refined_text']}")
PYTHON
tail -8 "$HOME/.dq_transcribe/server.log" | grep -v "GET /api"
