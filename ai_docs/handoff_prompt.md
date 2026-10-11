# Handoff prompt

Paste this (or point a new session at this file) to resume work.

---

You are continuing work on **dq_transcribe**, a local-first audio recording and transcription app, in the private repo `mizraith/dq_transcribe`.

**Read first:** `ai_docs/guidelines.md` (coding standards and rules) and `ai_docs/memory.md` (facts, decisions, open items).

**Current state:** the folder scaffold exists, plus a standard-library HTTP server (`src/dq_transcribe/server.py`), a browser microphone test page (`src/dq_transcribe/web/mic_test.html`), shared settings in `constants.py`, and unit tests in `tests/`. There is no transcription or database code yet. The mic test has been unit-tested for the server side only; the browser recording has not been run on the tablet.

**Environment:** the owner works from a Lenovo Idea Tab (Android 16, 8 GB RAM) with the Google Play build of Termux. There is no Linux container, and Termux:API is not used. You work in a cloud workspace and cannot connect to the tablet directly. The owner does not want to copy and paste code or commands.

**Running things on the tablet (the relay):** write a shell script, then run `COMMIT_TRAILERS="<trailers>" bash scripts/run_on_device.sh path/to/task.sh [wait_seconds]`. It commits the script to `device_tasks/` on `main`, and the tablet's `scripts/device_agent.sh` (which the owner starts once in Termux and leaves running) pulls it, runs it from the repo root, and publishes the output as a report on the `device-reports` branch. The helper prints the report. Round trips take roughly 15 to 40 seconds. If no report arrives, the agent is probably stopped: ask the owner to run `bash ~/dq_transcribe/scripts/device_agent.sh`. Start with read-only probe scripts. Tasks run unattended with the owner's permissions, so keep them small and non-destructive.

**Next steps (confirm with the owner before building):**
0. Confirm the device agent is running on the tablet by queueing a read-only probe (architecture, Python version, repo commit, free memory).
1. Mic test: start the server on the tablet via a queued task, then the owner opens `http://localhost:8000` in Chrome and taps Record (the only step that needs the owner). Check the saved file through another probe, or get the exact error text.
2. Add conversion of uploaded audio to 16 kHz mono WAV with ffmpeg.
3. Build the whisper.cpp transcription backend behind a small interface, and measure model speed on the tablet.
4. Add SQLite storage with edit support, then a local UI for viewing and editing notes.

**Standards reminder:** readable names, full docstrings and file headers, no magic strings (use `constants.py`), platform-neutral core. State clearly what you could not test.

**Before ending a session:** update `ai_docs/memory.md` and this file so the next session starts current.
