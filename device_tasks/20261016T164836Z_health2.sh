#!/usr/bin/env bash
# Read-only: is the accurate (small.en) whisper pass up?
grep -iE "whisper|refine" "$HOME/.dq_transcribe/server.log" | head -12
ps -ef | grep whisper-server | grep -v grep | wc -l
