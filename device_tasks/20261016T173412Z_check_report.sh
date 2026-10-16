#!/usr/bin/env bash
# Read-only: the running DQ serves the 12 pt coloured printout (template read per request).
git log -1 --format="repo at %h"
curl -s -m 8 "http://127.0.0.1:8000/event-summary?all=1&suite_meet_id=current&event=1" | grep -c "status-declined\|width: 100%"
