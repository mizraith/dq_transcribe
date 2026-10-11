#!/usr/bin/env bash
# Read-only: confirm the agent link and what the start script reports.
bash scripts/start_dq.sh status
ls -l "$PREFIX/bin/dq_transcribe" 2>&1
command -v termux-wake-lock termux-open-url
ls ~/storage 2>&1 | head
tail -3 ~/.dq_transcribe/server.log
