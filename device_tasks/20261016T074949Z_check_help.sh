#!/usr/bin/env bash
# Confirm the running app serves the "?" help pop-ups (web files are read per request; no restart).
git log -1 --format="repo at %h"
curl -s http://127.0.0.1:8000/app.js | grep -c "function showHelp"
curl -s http://127.0.0.1:8000/dq_view.js | grep -c "DQ_FILTER_HELP"
