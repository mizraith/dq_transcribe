#!/usr/bin/env bash
# Officials Sign-In: read-only probe. Why did admin_assistant open only DQ Transcribe?
# Shows where the command points, the script it runs, and whether the main page answers.
set -uo pipefail
for name in admin_assistant officials_signup; do
  path="$(command -v "$name" || true)"
  echo "$name -> ${path:-not found} -> $(readlink -f "$path" 2>/dev/null)"
done
target="$(readlink -f "$(command -v admin_assistant)" 2>/dev/null)"
[ -n "$target" ] && grep -n "MAIN_PAGE_URL\|COACH_DQ\|SIGNIN_OPEN_TABS\|open_browser" "$target"
echo "repo code: $(git log -1 --format='%h %s')"
python3 - <<'PY'
import urllib.request
page = urllib.request.urlopen("http://127.0.0.1:8010/", timeout=5).read()
print("main page answers:", b"app-launcher" in page)
PY
pgrep -af "officials_signin|dq_transcribe" | cut -c1-120
tail -5 "$HOME/.officials_signin/server.log"
