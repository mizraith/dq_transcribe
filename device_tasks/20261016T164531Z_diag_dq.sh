#!/usr/bin/env bash
# Read-only: why is port 8000 busy and DQ not answering?
ps -ef | grep -E "dq_transcribe|whisper|officials_signin|python" | grep -v grep | cut -c1-200
echo "--- curl"
curl -s -m 5 -o /dev/null -w "8000: %{http_code}\n" http://127.0.0.1:8000/
curl -s -m 5 -o /dev/null -w "8010: %{http_code}\n" http://127.0.0.1:8010/
echo "--- server.log tail"
tail -25 "$HOME/.dq_transcribe/server.log"
