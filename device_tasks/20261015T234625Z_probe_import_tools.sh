#!/usr/bin/env bash
# Read-only: which tools for reading Meet Manager files (PDF, HTML, Access database) are available?
for tool in pdftotext mdb-export mdb-tables unzip; do
  printf '%-12s %s\n' "$tool" "$(command -v $tool || echo missing)"
done
python -c "import pypdf; print('pypdf', pypdf.__version__)" 2>&1 | tail -1
for package in poppler mdbtools; do
  printf '%s: ' "$package"; (apt-cache policy "$package" 2>/dev/null | sed -n '2,3p' | tr -s ' ' | tr '\n' ' '); echo
done
python --version
