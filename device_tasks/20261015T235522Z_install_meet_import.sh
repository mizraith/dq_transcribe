#!/usr/bin/env bash
# Install the readers for Meet Manager files (PDF: poppler, Hy-Tek database: mdbtools),
# then restart the app so it runs the Meet Manager import. No timing test.
yes | pkg install -y poppler mdbtools > "$HOME/.dq_transcribe/pkg_install.log" 2>&1
echo "pkg install exit: $?"
for tool in pdftotext mdb-export mdb-tables; do printf '%-11s %s\n' "$tool" "$(command -v $tool || echo MISSING)"; done
pkill -f "python -m dq_transcribe" 2>/dev/null && sleep 2
PYTHONPATH=src nohup python -m dq_transcribe > "$HOME/.dq_transcribe/server.log" 2>&1 &
disown
for i in $(seq 1 30); do
  grep -q "whisper-server ready: ggml-small.en" "$HOME/.dq_transcribe/server.log" && grep -q "whisper-server ready: ggml-base" "$HOME/.dq_transcribe/server.log" && break
  sleep 1
done
git log -1 --format="running %h"
grep -E "Refine pass|whisper-server ready|Error|Traceback" "$HOME/.dq_transcribe/server.log" | head
curl -s -o /dev/null -w "page status %{http_code}\n" http://127.0.0.1:8000/
curl -s -o /dev/null -w "meet script status %{http_code}\n" http://127.0.0.1:8000/meet_view.js
curl -s http://127.0.0.1:8000/api/dqs | python -c "import json,sys,collections;d=json.load(sys.stdin)['dqs'];print(len(d),'DQs', dict(collections.Counter(x['status'] for x in d)))"
