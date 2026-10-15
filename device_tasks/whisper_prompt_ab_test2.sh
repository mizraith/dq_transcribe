#!/usr/bin/env bash
# Read-only A/B test, round 2: prompts without example numbers (so numbers cannot
# leak), on whole clips and on clip 4's last turn. Temp files only under ~/.dq_transcribe/tmp.
WHISPER_DIRECTORY="$HOME/.dq_transcribe/whisper.cpp"
CLI="$WHISPER_DIRECTORY/build/bin/whisper-cli"
MODEL="$WHISPER_DIRECTORY/models/ggml-base.bin"
TMP="$HOME/.dq_transcribe/tmp"; mkdir -p "$TMP"
PROMPT_WORDS="Possible DQ. Event, heat, lane. One hand touch, alternating kick, butterfly kick, false start, no touch at turn. Accepted. Acknowledged. Copy."
export LD_LIBRARY_PATH="$WHISPER_DIRECTORY/build/bin"
path_of() { python -c "import sqlite3,os;print(sqlite3.connect(os.path.expanduser('~/.dq_transcribe/notes.db')).execute('select audio_filename from clips where id=$1').fetchone()[0])"; }
run() { echo "-- $1 --"; shift; "$CLI" -m "$MODEL" -t 4 -l en -nt -sns "$@" 2>/dev/null; echo; }
C4="$HOME/.dq_transcribe/recordings/$(path_of 4)"
C6="$HOME/.dq_transcribe/recordings/$(path_of 6)"
ffmpeg -loglevel error -y -i "$C4" -ss 6.65 -to 14.4 "$TMP/c4_turn3.wav"
ffmpeg -loglevel error -y -i "$C6" -ss 0 -to 13.75 "$TMP/c6_turn1.wav"
for f in "$C4" "$TMP/c4_turn3.wav" "$C6" "$TMP/c6_turn1.wav"; do
  echo "== $(basename "$f") =="
  run "no prompt, suppress non-speech" -f "$f"
  run "word-only prompt" -f "$f" --prompt "$PROMPT_WORDS"
done
rm -f "$TMP/c4_turn3.wav" "$TMP/c6_turn1.wav"
