#!/usr/bin/env bash
# Start downloading the whisper "small.en" model (~466 MB) in the background, into
# ~/.dq_transcribe/whisper.cpp/models, for an accuracy/speed comparison with "base".
WHISPER_DIRECTORY="$HOME/.dq_transcribe/whisper.cpp"
LOG="$HOME/.dq_transcribe/model_download.log"
cd "$WHISPER_DIRECTORY" || exit 1
if [ -f models/ggml-small.en.bin ]; then echo "already downloaded"; ls -l models/ggml-small.en.bin; exit 0; fi
nohup bash models/download-ggml-model.sh small.en > "$LOG" 2>&1 &
disown
sleep 5
echo "download started"; tail -3 "$LOG"; df -h "$HOME" | tail -1
