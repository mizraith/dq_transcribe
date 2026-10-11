#!/usr/bin/env bash
# Delete the temporary rulebook-import branch on GitHub (its file is now on main).
git push origin --delete rulebook-import 2>&1
