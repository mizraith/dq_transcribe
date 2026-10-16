#!/usr/bin/env bash
# Confirm the running app serves the new Reset Demo button (web files are read per request; no restart).
git log -1 --format="repo at %h"
curl -s http://127.0.0.1:8000/meet.js 2>/dev/null | grep -c "Reset Demo" || true
for route in $(curl -s http://127.0.0.1:8000/ | grep -o 'src="[^"]*"' | cut -d'"' -f2); do
  printf "%s: " "$route"; curl -s "http://127.0.0.1:8000$route" | grep -c "Reset Demo"
done
