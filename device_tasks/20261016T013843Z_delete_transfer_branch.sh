#!/usr/bin/env bash
# Delete the temporary transfer-candy-meet branch on GitHub (it held the Hy-Tek backup for
# one transfer; the cloud workspace isn't allowed to delete branches).
git push -q origin --delete transfer-candy-meet && echo "deleted transfer-candy-meet"
git ls-remote --heads origin | grep -c transfer-candy-meet || true
