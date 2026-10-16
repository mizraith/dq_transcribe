#!/usr/bin/env bash
# Restart the app to install the coach page, then check it from the tablet itself:
# turn it on, open it on the tablet's Wi-Fi address, then turn it off again (owner decides when to serve).
pkill -f "python -m dq_transcribe" 2>/dev/null && sleep 2
PYTHONPATH=src nohup python -m dq_transcribe > "$HOME/.dq_transcribe/server.log" 2>&1 &
disown
for i in $(seq 1 40); do
  grep -q "whisper-server ready: ggml-small.en" "$HOME/.dq_transcribe/server.log" && grep -q "whisper-server ready: ggml-base" "$HOME/.dq_transcribe/server.log" && break
  sleep 1
done
git log -1 --format="running %h"
grep -E "whisper-server ready|Error|Traceback" "$HOME/.dq_transcribe/server.log" | head
curl -s -o /dev/null -w "admin page %{http_code}\n" http://127.0.0.1:8000/
STATUS=$(curl -s -X POST -H "Content-Type: application/json" -d '{"enabled": true}' http://127.0.0.1:8000/api/coach-page)
echo "$STATUS" | python -c "import json,sys;s=json.load(sys.stdin)['coach_page'];print('running', s['running'], 'urls', s['urls'], 'error', s['error'])"
URL=$(echo "$STATUS" | python -c "import json,sys;s=json.load(sys.stdin)['coach_page'];print(s['urls'][0] if s['urls'] else '')")
if [ -n "$URL" ]; then
  curl -s -o /dev/null -w "coach page on Wi-Fi address %{http_code}\n" "$URL"
  curl -s "$URL" | grep -o "Meet password" | head -1
  curl -s -o /dev/null -w "admin NOT reachable on Wi-Fi address: %{http_code}\n" --max-time 3 "${URL%:*}:8000/" || echo "admin not reachable on Wi-Fi address (good)"
fi
curl -s -X POST -H "Content-Type: application/json" -d '{"enabled": false}' http://127.0.0.1:8000/api/coach-page | python -c "import json,sys;print('coach page left off:', not json.load(sys.stdin)['coach_page']['running'])"
curl -s http://127.0.0.1:8000/api/meets | python -c "import json,sys;d=json.load(sys.stdin);print('active meet', [m['name'] for m in d['meets'] if m['id']==d['active_meet_id']])"
