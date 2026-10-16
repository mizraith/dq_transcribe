#!/usr/bin/env bash
# Confirm the running app serves the bordered 2-per-page slips (web files are read per request; no restart).
git log -1 --format="repo at %h"
curl -s "http://127.0.0.1:8000/slips?print_requested=1&layout=two_up" | grep -c "border: 1px solid #000"
