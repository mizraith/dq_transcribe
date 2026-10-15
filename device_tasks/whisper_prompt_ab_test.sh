#!/usr/bin/env bash
# Read-only A/B test: transcribe real clips 4 and 6 with the current settings and
# with a domain prompt plus non-speech suppression. Writes only temp files under
# ~/.dq_transcribe/tmp.
WHISPER_DIRECTORY="$HOME/.dq_transcribe/whisper.cpp"
CLI="$WHISPER_DIRECTORY/build/bin/whisper-cli"
MODEL="$WHISPER_DIRECTORY/models/ggml-base.bin"
PROMPT="Possible DQ. Event 4, heat 5, lane 6. One hand touch. Event 12, heat 3, lane 2, alternating kick. Accepted. Acknowledged."
export LD_LIBRARY_PATH="$WHISPER_DIRECTORY/build/bin"
for clip_id in 4 6; do
  file=$(python -c "import sqlite3,os;print(sqlite3.connect(os.path.expanduser('~/.dq_transcribe/notes.db')).execute('select audio_filename from clips where id=$clip_id').fetchone()[0])")
  path="$HOME/.dq_transcribe/recordings/$file"
  echo "== clip $clip_id ($file) =="
  echo "-- current settings --"
  "$CLI" -m "$MODEL" -f "$path" -t 4 -l en -nt 2>/dev/null
  echo "-- prompt + suppress non-speech --"
  "$CLI" -m "$MODEL" -f "$path" -t 4 -l en -nt -sns --prompt "$PROMPT" 2>/dev/null
done
