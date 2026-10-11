# Handoff prompt

Paste this (or point a new session at this file) to resume work.

---

You are continuing work on **dq_transcribe**, a local-first audio recording and transcription app, in the private repo `mizraith/dq_transcribe`.

**Read first:** `ai_docs/guidelines.md` (coding standards and rules) and `ai_docs/memory.md` (facts, decisions, open items).

**Current state:** the folder scaffold exists, plus a standard-library HTTP server (`src/dq_transcribe/server.py`), a browser microphone test page (`src/dq_transcribe/web/mic_test.html`), shared settings in `constants.py`, and unit tests in `tests/`. There is no transcription or database code yet. The mic test has been unit-tested for the server side only; the browser recording has not been run on the tablet.

**Environment:** the owner works from a Lenovo Idea Tab (Android 16, 8 GB RAM) with the Google Play build of Termux. There is no Linux container, and Termux:API is not used. You work in a cloud workspace and cannot run anything on the tablet. You deliver by committing and pushing to this repo; the owner runs `git pull` in Termux. The owner does not want to copy and paste code.

**Next steps (confirm with the owner before building):**
1. Owner runs the mic test: `PYTHONPATH=src python -m dq_transcribe`, then opens `http://localhost:8000` in Chrome and taps Record. Get the result, or the exact error text.
2. Add conversion of uploaded audio to 16 kHz mono WAV with ffmpeg.
3. Build the whisper.cpp transcription backend behind a small interface, and measure model speed on the tablet.
4. Add SQLite storage with edit support, then a local UI for viewing and editing notes.

**Standards reminder:** readable names, full docstrings and file headers, no magic strings (use `constants.py`), platform-neutral core. State clearly what you could not test.

**Before ending a session:** update `ai_docs/memory.md` and this file so the next session starts current.
