#!/usr/bin/env bash
# Read-only: stored officials (names only) and the newest scans' name-related OCR lines.
# Member IDs are blanked. Nothing is changed.
echo "== code"; git log -1 --format='%h %ci'
echo "== stored officials"
python3 - <<'PYTHON'
import sqlite3, os
db = sqlite3.connect(os.path.expanduser("~/.officials_signin/signin.db"))
for row in db.execute("SELECT id, name, lsc, club, card_meet_id, updated_at FROM officials ORDER BY id"):
    print(row)
PYTHON
DIAGNOSTICS="$HOME/.officials_signin/diagnostics"
echo "== scans"; ls -1 "$DIAGNOSTICS" | tail -6
for folder in $(ls -1d "$DIAGNOSTICS"/*/ 2>/dev/null | tail -3); do
  echo; echo "######## $(basename "$folder")  stills/frames: $(ls "$folder" | grep -c jpg)"
  python3 - "$folder/records.jsonl" <<'PYTHON'
import json, re, sys
ID = re.compile(r"\b(?=[A-Z0-9]*\d)[A-Z0-9]{10,16}\b")
for line in open(sys.argv[1]):
    r = json.loads(line)
    kind = r.get("kind")
    if kind in ("frame",):
        continue
    if kind == "camera":
        s = r.get("settings") or {}
        print("CAMERA", r.get("facing"), r.get("video_size"), "focus:", (r.get("capabilities") or {}).get("focusMode"))
    elif kind == "guide":
        print("GUIDE", r.get("state"), "sharp", r.get("sharpness"), "motion", r.get("motion"), "screen", r.get("screen"), "t", r.get("elapsed_ms"))
    elif kind == "still":
        print("STILL rank", r.get("rank"), "sharp", r.get("sharpness"), "box", r.get("box"), "t", r.get("elapsed_ms"))
    elif kind == "orientation":
        print("ORIENT", r)
    elif kind == "pass":
        text = ID.sub("[ID]", r.get("text", ""))
        lines = [l for l in text.splitlines() if l.strip()]
        print("PASS %s layout=%s rot=%s size=%s ocr=%sms card=%s t=%s" % (r.get("pass"), r.get("layout"), r.get("rotation"), r.get("frame_size"), r.get("ocr_ms"), r.get("card_words"), r.get("elapsed_ms")))
        for l in lines[:12]:
            print("    |", l[:110])
    else:
        print(kind.upper(), {k: v for k, v in r.items() if k != "kind"})
PYTHON
done
