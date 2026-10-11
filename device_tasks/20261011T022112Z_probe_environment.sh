#!/usr/bin/env bash
# Read-only probe of the tablet's development environment. Changes nothing.

echo "== system =="
uname -srm
echo "cpu cores: $(nproc 2>&1)"
free -h 2>&1 | head -3
echo
echo "== storage (home) =="
df -h "$HOME" 2>&1 | tail -2
echo
echo "== tools =="
for tool in python python3 pip git gh ffmpeg clang cmake make node; do
  if command -v "$tool" >/dev/null 2>&1; then
    printf '%-8s %s\n' "$tool" "$("$tool" --version 2>&1 | head -1)"
  else
    printf '%-8s MISSING\n' "$tool"
  fi
done
echo
echo "== repo =="
git log --oneline -3 2>&1
echo "recordings: $(ls "$HOME/.dq_transcribe/recordings" 2>/dev/null | wc -l) file(s)"
echo
echo "== package import check =="
PYTHONPATH=src python -c "import dq_transcribe, dq_transcribe.server; print('dq_transcribe', dq_transcribe.__version__, 'imports OK')" 2>&1
echo
echo "== unit tests =="
PYTHONPATH=src python -m unittest discover -s tests 2>&1 | tail -4
