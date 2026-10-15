#!/usr/bin/env bash
# Read-only for the app: export clips 25-52 (text, timings, raw whisper JSON) to a
# JSON file and push it to the temporary branch "data-export" from a throwaway worktree.
set -euo pipefail
BRANCH="data-export"
WT="$HOME/.dq_transcribe/tmp/export_worktree"
git worktree remove --force "$WT" 2>/dev/null || true; rm -rf "$WT"
git fetch -q origin main
git worktree add -q -B "$BRANCH" "$WT" origin/main
mkdir -p "$WT/data_exports"
python - "$WT/data_exports/clips_25_52.json" <<'PYTHON'
import json, os, sqlite3, sys
db = sqlite3.connect(os.path.expanduser("~/.dq_transcribe/notes.db")); db.row_factory = sqlite3.Row
clips = [dict(r) for r in db.execute("select * from clips where id between 25 and 52 order by id")]
for c in clips:
    c["utterances"] = [dict(r) for r in db.execute("select * from utterances where clip_id=? order by position", (c["id"],))]
json.dump(clips, open(sys.argv[1], "w"), indent=1)
print(len(clips), "clips,", sum(len(c["utterances"]) for c in clips), "utterances,", os.path.getsize(sys.argv[1]), "bytes")
PYTHON
cd "$WT"; git add data_exports
git -c user.name="dq_transcribe device agent" -c user.email="device-agent@localhost" commit -q -m "Export clips 25-52"
git push -q -f origin "$BRANCH"; cd - >/dev/null
git worktree remove --force "$WT"; git branch -D "$BRANCH" >/dev/null
echo pushed
