#!/usr/bin/env bash
# Read-only for the app: copy WAVs of clips 26, 29, 38, 50 and 52 to the temporary
# branch "data-export" (throwaway worktree) for noise analysis. Also send the newest
# capture info so the input settings can be checked.
set -euo pipefail
BRANCH="data-export"; WT="$HOME/.dq_transcribe/tmp/export_worktree"
git worktree remove --force "$WT" 2>/dev/null || true; rm -rf "$WT"
git fetch -q origin main; git worktree add -q -B "$BRANCH" "$WT" origin/main
mkdir -p "$WT/data_exports/wav"
python - "$WT/data_exports/wav" <<'PYTHON'
import os, shutil, sqlite3, sys, json
db = sqlite3.connect(os.path.expanduser("~/.dq_transcribe/notes.db"))
for clip_id in (26, 29, 38, 50, 52):
    name, info = db.execute("select audio_filename, capture_info_json from clips where id=?", (clip_id,)).fetchone()
    shutil.copy(os.path.expanduser(f"~/.dq_transcribe/recordings/{name}"), f"{sys.argv[1]}/clip_{clip_id}.wav")
    print(clip_id, json.loads(info or "{}"))
PYTHON
cd "$WT"; git add -f data_exports
git -c user.name="dq_transcribe device agent" -c user.email="device-agent@localhost" commit -q -m "Export sample WAVs"
git push -q -f origin "$BRANCH"; cd - >/dev/null
git worktree remove --force "$WT"; git branch -D "$BRANCH" >/dev/null; echo pushed
