#!/usr/bin/env bash
# Read-only: list whisper-cli options related to prompts and non-speech tokens,
# and show recent transcripts from the app database.
WHISPER_DIRECTORY="$HOME/.dq_transcribe/whisper.cpp"
LD_LIBRARY_PATH="$WHISPER_DIRECTORY/build/bin" "$WHISPER_DIRECTORY/build/bin/whisper-cli" --help 2>&1 \
  | grep -i -E "prompt|suppress|nst|no-speech|entropy|logprob|temperature|beam|best-of|vad" 
echo "--- whisper.cpp version ---"
git -C "$WHISPER_DIRECTORY" log -1 --format='%h %cd %s' 2>&1 | head -1
ls "$WHISPER_DIRECTORY/models" 2>&1
echo "--- recent utterances ---"
python - <<'PYTHON'
import sqlite3, os
db = sqlite3.connect(os.path.expanduser("~/.dq_transcribe/notes.db"))
rows = db.execute("""SELECT c.id, c.started_at, round(c.duration_seconds,1), c.trashed_at IS NOT NULL, u.position,
    round(u.start_seconds,1), round(u.end_seconds,1), u.text FROM clips c LEFT JOIN utterances u ON u.clip_id = c.id
    ORDER BY c.id DESC, u.position LIMIT 60""").fetchall()
for row in rows:
    print(row)
print("clip count:", db.execute("SELECT count(*) FROM clips").fetchone()[0])
PYTHON
