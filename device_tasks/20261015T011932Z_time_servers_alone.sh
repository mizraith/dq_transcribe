#!/usr/bin/env bash
# Time each running whisper-server on clip 6's audio, one at a time (no overlap).
f="$HOME/.dq_transcribe/recordings/$(python -c "import sqlite3,os;print(sqlite3.connect(os.path.expanduser('~/.dq_transcribe/notes.db')).execute('select audio_filename from clips where id=6').fetchone()[0])")"
for port in 8178 8179 8178 8179; do
  s=$(date +%s.%N)
  text=$(curl -s -F file=@"$f" -F response_format=json -F temperature=0.0 "http://127.0.0.1:$port/inference")
  e=$(date +%s.%N)
  python -c "print('port $port', round($e-$s,1), 's', '''$text'''[:110])"
done
