#!/usr/bin/env bash
# Upload temporary copies of real clips 4, 5, 6 (from the trash), measure the
# two-pass timings, print draft vs refined text, then delete the copies.
python - <<'PYTHON'
import json, os, sqlite3, time, urllib.request
BASE = "http://127.0.0.1:8000/api/clips"
db = sqlite3.connect(os.path.expanduser("~/.dq_transcribe/notes.db"))
print("clips in list:", [c["id"] for c in json.load(urllib.request.urlopen(BASE))["clips"]])
print("clips in trash:", [c["id"] for c in json.load(urllib.request.urlopen(BASE + "?view=trash"))["clips"]])
copies = {}
start = time.time()
for source_id in (4, 5, 6):
    name = db.execute("select audio_filename from clips where id=?", (source_id,)).fetchone()[0]
    data = open(os.path.expanduser(f"~/.dq_transcribe/recordings/{name}"), "rb").read()
    request = urllib.request.Request(BASE, data=data, headers={"Content-Type": "audio/wav"})
    copies[json.load(urllib.request.urlopen(request))["clip_id"]] = source_id
seen_draft = {}
while time.time() - start < 240:
    clips = {c["id"]: c for c in json.load(urllib.request.urlopen(BASE))["clips"] if c["id"] in copies}
    for clip_id, clip in clips.items():
        if clip["status"] == "done" and clip_id not in seen_draft:
            seen_draft[clip_id] = round(time.time() - start, 1)
    if len(clips) == len(copies) and all(c["status"] == "done" and c["refine_status"] in ("done", "failed", "skipped") for c in clips.values()):
        break
    time.sleep(1)
print(f"all finished after {time.time() - start:.1f} s")
for clip_id, source_id in copies.items():
    c = clips[clip_id]
    print(f"copy of clip {source_id}: {c['duration_seconds']:.1f} s audio | draft shown at {seen_draft.get(clip_id)} s "
          f"(draft {c['transcribe_seconds']:.1f} s) | refine {c['refine_status']} {c['refine_seconds'] or 0:.1f} s, done at {round(time.time()-start,1)}")
    for u in c["utterances"]:
        print(f"   draft:   {u['original_text']}")
        print(f"   refined: {u['refined_text']}")
for clip_id in copies:
    for action in ("trash", "delete"):
        urllib.request.urlopen(urllib.request.Request(f"{BASE}/{clip_id}/{action}", data=b"x", method="POST")).read()
print("deleted the test copies")
PYTHON
