#!/usr/bin/env bash
# Create and push the annotated ALPHA release tag v0.2.0-alpha on the ALPHA commit
# (the cloud session's proxy refuses tag pushes). Read-only otherwise.
ALPHA_COMMIT="ba6383eddd62352e6aaeb1cf64a0ed7193fbd748"
TAG_NAME="v0.2.0-alpha"
git fetch -q origin main
git tag -a "$TAG_NAME" "$ALPHA_COMMIT" -m "ALPHA: Admin Assistant suite with DQ Transcribe (version 0.2.0a1), as used at the Candy Meet 2026-10-16" 2>&1
git push origin "$TAG_NAME" 2>&1
git ls-remote --tags origin 2>&1
