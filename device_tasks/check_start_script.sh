#!/usr/bin/env bash
# Read-only: show what the new start script reports on the tablet.
bash scripts/start_dq.sh status
ls -l "$PREFIX/bin/dq_transcribe" 2>&1
command -v termux-wake-lock termux-open-url
