#!/usr/bin/env bash
# Restart the app server with the new code, then compare whisper base vs small.en
# (both with the new prompt) on real clips 4 and 6. Temp files only.
SERVER_PATTERN="python -m dq_transcribe"
pkill -f "$SERVER_PATTERN" 2>/dev/null && sleep 1
PYTHONPATH=src nohup python -m dq_transcribe > "$HOME/.dq_transcribe/server.log" 2>&1 &
disown
sleep 3
git log -1 --format="server running %h"
curl -s -o /dev/null -w "page status %{http_code}\n" http://127.0.0.1:8000/
WHISPER_DIRECTORY="$HOME/.dq_transcribe/whisper.cpp"
export LD_LIBRARY_PATH="$WHISPER_DIRECTORY/build/bin"
CLI="$WHISPER_DIRECTORY/build/bin/whisper-cli"
PROMPT="$(tr '\n' ' ' < src/dq_transcribe/data/whisper_prompt.txt)"
ls -l "$WHISPER_DIRECTORY/models/ggml-small.en.bin" 2>&1; tail -c 300 "$HOME/.dq_transcribe/model_download.log"; echo
path_of() { python -c "import sqlite3,os;print(sqlite3.connect(os.path.expanduser('~/.dq_transcribe/notes.db')).execute('select audio_filename from clips where id=$1').fetchone()[0])"; }
for clip_id in 4 6; do
  f="$HOME/.dq_transcribe/recordings/$(path_of $clip_id)"
  for model in base small.en; do
    start=$(date +%s.%N)
    text=$("$CLI" -m "$WHISPER_DIRECTORY/models/ggml-$model.bin" -f "$f" -t 4 -l en -nt -sns --prompt "$PROMPT" 2>/dev/null | tr -s ' \n' ' ')
    end=$(date +%s.%N)
    printf 'clip %s | %-8s | %5.1f s | %s\n' "$clip_id" "$model" "$(python -c "print($end-$start)")" "$text"
  done
done
