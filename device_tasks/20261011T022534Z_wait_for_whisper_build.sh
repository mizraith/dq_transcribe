#!/usr/bin/env bash
# Wait (up to ~9 minutes) for the whisper.cpp build to finish, then report status.

APP_DIRECTORY="$HOME/.dq_transcribe"
BUILD_LOG="$APP_DIRECTORY/whisper_build.log"
RESULT_MARKER="$APP_DIRECTORY/whisper_build_result.txt"
MAX_WAIT_SECONDS=540
CHECK_INTERVAL_SECONDS=10

waited=0
while [ ! -f "$RESULT_MARKER" ] && [ "$waited" -lt "$MAX_WAIT_SECONDS" ]; do
  sleep "$CHECK_INTERVAL_SECONDS"
  waited=$((waited + CHECK_INTERVAL_SECONDS))
done

if [ -f "$RESULT_MARKER" ]; then
  echo "result: $(cat "$RESULT_MARKER")"
else
  echo "result: still running after ${waited}s"
fi
echo "--- last log lines ---"
tail -8 "$BUILD_LOG"
echo "--- artifacts ---"
ls -lh "$APP_DIRECTORY/whisper.cpp/build/bin/" 2>/dev/null | head -20
ls -lh "$APP_DIRECTORY/whisper.cpp/models/"ggml-*.bin 2>/dev/null
