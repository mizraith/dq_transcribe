#!/usr/bin/env bash
# Download the 2026 USA Swimming rulebook PDF on the tablet (the cloud workspace
# cannot reach usaswimming.org) and push it to the temporary branch
# "rulebook-import" from a throwaway worktree. The main checkout is not touched.
set -euo pipefail

RULEBOOK_URL="https://www.usaswimming.org/rulebook"
IMPORT_BRANCH="rulebook-import"
WORKTREE_DIRECTORY="$HOME/.dq_transcribe/tmp/rulebook_worktree"
PDF_NAME="usa-swimming-rulebook-2026_downloaded-$(date +%Y-%m-%d).pdf"

git worktree remove --force "$WORKTREE_DIRECTORY" 2>/dev/null || true
rm -rf "$WORKTREE_DIRECTORY"
git fetch -q origin main
git worktree add -q -B "$IMPORT_BRANCH" "$WORKTREE_DIRECTORY" origin/main
mkdir -p "$WORKTREE_DIRECTORY/rulebook"

curl -sSL --fail --max-time 120 -o "$WORKTREE_DIRECTORY/rulebook/$PDF_NAME" -w "final URL: %{url_effective}\nHTTP %{http_code}\n" "$RULEBOOK_URL"
head -c 5 "$WORKTREE_DIRECTORY/rulebook/$PDF_NAME"; echo
ls -l "$WORKTREE_DIRECTORY/rulebook/$PDF_NAME"
sha256sum "$WORKTREE_DIRECTORY/rulebook/$PDF_NAME"

cd "$WORKTREE_DIRECTORY"
git add rulebook
git -c user.name="dq_transcribe device agent" -c user.email="device-agent@localhost" \
  commit -q -m "Import 2026 USA Swimming rulebook (downloaded on tablet)"
git push -q -f origin "$IMPORT_BRANCH"
echo "pushed $IMPORT_BRANCH"
cd - >/dev/null
git worktree remove --force "$WORKTREE_DIRECTORY"
git branch -D "$IMPORT_BRANCH" >/dev/null
