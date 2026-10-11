#!/usr/bin/env bash
# Inspect the newest recording and test conversion to 16 kHz mono WAV.
# Writes only one temporary file under ~/.dq_transcribe/tmp.

RECORDINGS_DIRECTORY="$HOME/.dq_transcribe/recordings"
SCRATCH_DIRECTORY="$HOME/.dq_transcribe/tmp"
WAV_SAMPLE_RATE_HZ=16000
WAV_CHANNELS=1

echo "== recordings =="
ls -lh "$RECORDINGS_DIRECTORY" 2>&1

newest="$(ls -t "$RECORDINGS_DIRECTORY"/* 2>/dev/null | head -1)"
if [ -z "$newest" ]; then
  echo "No recordings found."
  exit 1
fi

echo
echo "== newest: $(basename "$newest") =="
ffprobe -hide_banner "$newest" 2>&1 | grep -E "Duration|Stream"

mkdir -p "$SCRATCH_DIRECTORY"
converted="$SCRATCH_DIRECTORY/conversion_test.wav"
ffmpeg -hide_banner -loglevel error -y -i "$newest" -ar "$WAV_SAMPLE_RATE_HZ" -ac "$WAV_CHANNELS" "$converted"
echo
echo "== conversion to ${WAV_SAMPLE_RATE_HZ} Hz mono WAV =="
ls -lh "$converted"
ffprobe -hide_banner "$converted" 2>&1 | grep -E "Duration|Stream"
rm -f "$converted"
