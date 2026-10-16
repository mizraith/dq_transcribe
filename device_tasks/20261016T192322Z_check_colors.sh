#!/usr/bin/env bash
# Read-only: the running DQ serves the new status colours (web files are read per request; no restart).
git log -1 --format="repo at %h"
curl -s -m 5 http://127.0.0.1:8000/ | grep -c "badge.status-upheld { background: #dbeafe"
