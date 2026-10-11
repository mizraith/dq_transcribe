#!/usr/bin/env bash
# Start building whisper.cpp and downloading the base model, in the background.
# Everything lives under ~/.dq_transcribe. Progress goes to whisper_build.log and a
# marker file records the outcome. Re-running resumes where it left off.

APP_DIRECTORY="$HOME/.dq_transcribe"
WHISPER_DIRECTORY="$APP_DIRECTORY/whisper.cpp"
BUILD_LOG="$APP_DIRECTORY/whisper_build.log"
RESULT_MARKER="$APP_DIRECTORY/whisper_build_result.txt"
REPOSITORY_URL="https://github.com/ggml-org/whisper.cpp"
MODEL_NAME="base"

mkdir -p "$APP_DIRECTORY"
rm -f "$RESULT_MARKER"

export WHISPER_DIRECTORY BUILD_LOG RESULT_MARKER REPOSITORY_URL MODEL_NAME

nohup bash -c '
  set -u
  {
    echo "== $(date -Is) start =="
    if [ ! -d "$WHISPER_DIRECTORY/.git" ]; then
      git clone --depth 1 "$REPOSITORY_URL" "$WHISPER_DIRECTORY" || { echo "FAILED: clone" > "$RESULT_MARKER"; exit 1; }
    fi
    cd "$WHISPER_DIRECTORY" || exit 1
    echo "== configure =="
    cmake -S . -B build -DCMAKE_BUILD_TYPE=Release || { echo "FAILED: cmake configure" > "$RESULT_MARKER"; exit 1; }
    echo "== build =="
    cmake --build build -j 4 --config Release || { echo "FAILED: cmake build" > "$RESULT_MARKER"; exit 1; }
    echo "== model =="
    if ! command -v curl >/dev/null 2>&1 && ! command -v wget >/dev/null 2>&1; then
      pkg install -y curl
    fi
    bash models/download-ggml-model.sh "$MODEL_NAME" || { echo "FAILED: model download" > "$RESULT_MARKER"; exit 1; }
    echo "== $(date -Is) done =="
    echo "DONE" > "$RESULT_MARKER"
  } > "$BUILD_LOG" 2>&1
' > /dev/null 2>&1 &
disown

sleep 5
echo "build started in the background"
echo "--- log so far ---"
tail -5 "$BUILD_LOG"
