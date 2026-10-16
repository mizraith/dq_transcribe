#!/usr/bin/env bash
# Create the Candy Meet on the tablet from the Hy-Tek Meet Manager backup the owner shared
# (fetched from the temporary branch transfer-candy-meet; main is not touched). The new meet
# becomes the active meet. The copied file is removed afterwards (the app keeps its own copy).
set -e
BRANCH=transfer-candy-meet
FILE="Swmm8Bkup10162026_Candy_Meet_Block_Party-01.zip"
INCOMING="$HOME/.dq_transcribe/incoming"
mkdir -p "$INCOMING"
git fetch -q origin "$BRANCH"
git show "FETCH_HEAD:transfer/$FILE" > "$INCOMING/$FILE"
ls -l "$INCOMING/$FILE" | awk '{print "fetched", $5, "bytes"}'
curl -s -X POST -H "Content-Type: application/octet-stream" --data-binary "@$INCOMING/$FILE" \
  "http://127.0.0.1:8000/api/meets/from-sheet?name=$FILE" \
  | python -c "import json,sys;r=json.load(sys.stdin);print(json.dumps(r, indent=1)[:1500])"
rm -f "$INCOMING/$FILE"
curl -s http://127.0.0.1:8000/api/meets | python -c "import json,sys;d=json.load(sys.stdin);[print(m['id'], m['name'], m['start_date'], 'ACTIVE' if m['id']==d['active_meet_id'] else '') for m in d['meets']]"
