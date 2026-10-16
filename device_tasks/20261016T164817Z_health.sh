#!/usr/bin/env bash
# Read-only health check of DQ Transcribe.
grep -E "whisper-server ready|Traceback" "$HOME/.dq_transcribe/server.log" | head
curl -s -m 5 -o /dev/null -w "DQ page %{http_code}\n" http://127.0.0.1:8000/
curl -s -m 5 http://127.0.0.1:8000/api/meets | python -c "import json,sys;d=json.load(sys.stdin);print('active meet', [m['name'] for m in d['meets'] if m['id']==d['active_meet_id']])"
