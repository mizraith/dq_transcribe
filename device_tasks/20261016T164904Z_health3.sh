#!/usr/bin/env bash
# Read-only: the start of DQ's log, and who holds the whisper ports.
head -30 "$HOME/.dq_transcribe/server.log" | cut -c1-200
ps -ef | grep whisper-server | grep -v grep | cut -c1-60
curl -s -m 3 -o /dev/null -w "8179: %{http_code}\n" http://127.0.0.1:8179/
curl -s -m 3 -o /dev/null -w "8178: %{http_code}\n" http://127.0.0.1:8178/
