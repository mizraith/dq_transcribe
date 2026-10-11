#!/usr/bin/env bash
# Transcribe the newest recording and the bundled JFK sample with whisper.cpp,
# timing both. Only writes a temporary WAV under ~/.dq_transcribe/tmp.

APP_DIRECTORY="$HOME/.dq_transcribe"
WHISPER_DIRECTORY="$APP_DIRECTORY/whisper.cpp"
WHISPER_CLI="$WHISPER_DIRECTORY/build/bin/whisper-cli"
MODEL_PATH="$WHISPER_DIRECTORY/models/ggml-base.bin"
SAMPLE_WAV="$WHISPER_DIRECTORY/samples/jfk.wav"
RECORDINGS_DIRECTORY="$APP_DIRECTORY/recordings"
SCRATCH_DIRECTORY="$APP_DIRECTORY/tmp"
THREAD_COUNT=4
LANGUAGE="en"

transcribe() {
  local label="$1" wav_path="$2" started finished
  echo "== $label =="
  started=$(date +%s.%N)
  LD_LIBRARY_PATH="$WHISPER_DIRECTORY/build/bin" "$WHISPER_CLI" \
    -m "$MODEL_PATH" -f "$wav_path" -t "$THREAD_COUNT" -l "$LANGUAGE" -nt 2>/dev/null
  finished=$(date +%s.%N)
  printf 'transcription took %.1f seconds\n\n' "$(echo "$finished - $started" | bc -l 2>/dev/null || python -c "print($finished - $started)")"
}

if [ ! -x "$WHISPER_CLI" ]; then
  echo "whisper-cli not found at $WHISPER_CLI"
  ls "$WHISPER_DIRECTORY/build/bin" 2>&1 | head -30
  exit 1
fi

transcribe "bundled sample (jfk.wav, about 11 s of audio)" "$SAMPLE_WAV"

newest="$(ls -t "$RECORDINGS_DIRECTORY"/* 2>/dev/null | head -1)"
if [ -n "$newest" ]; then
  mkdir -p "$SCRATCH_DIRECTORY"
  converted="$SCRATCH_DIRECTORY/transcribe_test.wav"
  ffmpeg -hide_banner -loglevel error -y -i "$newest" -ar 16000 -ac 1 "$converted"
  transcribe "your recording ($(basename "$newest"), about 5 s of audio)" "$converted"
  rm -f "$converted"
fi
