#!/usr/bin/env bash
# Read-only: why did officials_signup not come up from admin_assistant?
# Starts, stops and installs nothing.
echo "== shortcuts"
ls -la "$PREFIX/bin/officials_signup" "$PREFIX/bin/admin_assistant" "$PREFIX/bin/dq_transcribe" 2>&1
echo "== repo head"
git log -1 --format='%h %s'
ls -la scripts/start_signin.sh scripts/start_admin_assistant.sh 2>&1
echo "== python"
command -v python3 python; python3 --version 2>&1
echo "== processes"
pgrep -af "officials_signin|dq_transcribe|device_agent" 2>&1 | grep -v pgrep
echo "== status via script"
bash scripts/start_signin.sh status 2>&1
echo "== port 8010"
python3 - <<'PYTHON'
import urllib.request
try:
    print(urllib.request.urlopen("http://127.0.0.1:8010/api/state", timeout=3).read()[:200])
except Exception as error:
    print("no answer:", error)
PYTHON
echo "== data folder"
ls -la "$HOME/.officials_signin" 2>&1
echo "== server.log (last 40 lines)"
tail -40 "$HOME/.officials_signin/server.log" 2>&1
