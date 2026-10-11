# Handoff prompt

Paste this (or point a new session at this file) to resume work.

---

You are continuing work on **dq_transcribe**, a local-first audio recording and transcription app, in the private repo `mizraith/dq_transcribe`.

**Read first:** `ai_docs/guidelines.md` (coding standards and rules) and `ai_docs/memory.md` (facts, decisions, open items).

**Current state:** the repo is a scaffold. It has the folder layout, `src/dq_transcribe/constants.py`, `pyproject.toml`, `.gitignore`, a README, and `scripts/termux_setup.sh`. There is no application code yet.

**Environment:** the owner works from a Lenovo Idea Tab (Android 16, 8 GB RAM) with Termux installed. There is no Linux container on the device. You work in a cloud workspace and cannot run anything on the tablet. You deliver by committing and pushing to this repo; the owner runs `git pull` in Termux. The owner does not want to copy and paste code.

**Next steps (confirm with the owner before building):**
1. Have the owner run `scripts/termux_setup.sh` and report results, in particular whether `termux-microphone-record` works.
2. Build the whisper.cpp transcription backend behind a small interface, and measure model speed on the tablet.
3. Add SQLite storage with edit support.
4. Add a local web UI served on `localhost`.

**Standards reminder:** readable names, full docstrings and file headers, no magic strings (use `constants.py`), platform-neutral core. State clearly what you could not test.

**Before ending a session:** update `ai_docs/memory.md` and this file so the next session starts current.
