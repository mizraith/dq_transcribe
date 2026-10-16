#!/usr/bin/env bash
# Read-only: is the running sign-in server older than the code on disk?
echo "== repo head"; git log -1 --format='%h %ci %s'
echo "== last sign-in code commit"; git log -1 --format='%h %ci %s' -- src/officials_signin
echo "== sign-in server process start"
for pid in $(pgrep -f "python[0-9.]* -m officials_signin"); do ps -o pid,lstart,args -p "$pid" 2>/dev/null || ps -p "$pid"; done
echo "== does the served page config have session types?"
python3 - <<'PYTHON'
import urllib.request
try:
    body = urllib.request.urlopen("http://127.0.0.1:8010/signin.js", timeout=3).read().decode()
    print("sessionTypes in config:", "sessionTypes" in body)
except Exception as error:
    print("no answer:", error)
PYTHON
echo "== server.log tail"; tail -15 "$HOME/.officials_signin/server.log"
