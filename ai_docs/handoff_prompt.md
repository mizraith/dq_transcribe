# Handoff prompt

Paste this (or point a new session at this file) to resume work.

---

You are continuing work on **dq_transcribe**, a local-first audio recording and transcription app, in the private repo `mizraith/dq_transcribe`.

**Read first:** `ai_docs/guidelines.md` (coding standards and rules) and `ai_docs/memory.md` (facts, decisions, open items).

**Current state:** the folder scaffold exists, plus a standard-library HTTP server (`src/dq_transcribe/server.py`), a browser microphone test page (`src/dq_transcribe/web/mic_test.html`), shared settings in `constants.py`, and unit tests in `tests/`. There is no transcription or database code yet. On the tablet, verified: the mic test page records and uploads, ffmpeg converts to 16 kHz mono WAV, and whisper.cpp (built at `~/.dq_transcribe/whisper.cpp`, `base` model) transcribes correctly. These steps are not yet wired together inside the app.

**Environment:** the owner works from a Lenovo Idea Tab (Android 16, 8 GB RAM) with the Google Play build of Termux. There is no Linux container, and Termux:API is not used. You work in a cloud workspace and cannot connect to the tablet directly. The owner does not want to copy and paste code or commands.

**Running things on the tablet (the relay):** write a shell script, then run `COMMIT_TRAILERS="<trailers>" bash scripts/run_on_device.sh path/to/task.sh [wait_seconds]`. It commits the script to `device_tasks/` on `main`, and the tablet's `scripts/device_agent.sh` (which the owner starts once in Termux and leaves running) pulls it, runs it from the repo root, and publishes the output as a report on the `device-reports` branch. The helper prints the report. Round trips take roughly 15 to 40 seconds. If no report arrives, the agent is probably stopped: ask the owner to run `bash ~/dq_transcribe/scripts/device_agent.sh`. Start with read-only probe scripts. Tasks run unattended with the owner's permissions, so keep them small and non-destructive.

**Next steps (confirm with the owner before building):**
0. Confirm the device agent is running on the tablet by queueing a read-only probe (architecture, Python version, repo commit, free memory). Done once on 2026-10-10.
1. Mic test passed on 2026-10-10. Remaining unknown: reliability over long sessions (see open items in `ai_docs/memory.md`).
2. Add conversion of uploaded audio to 16 kHz mono WAV with ffmpeg.
3. Build the transcription backend (calls the whisper.cpp CLI, behind a small interface) in Python, and measure model speed repeatably on the tablet.
4. Add SQLite storage with edit support, then a local UI for viewing and editing notes.

**Standards reminder:** readable names, full docstrings and file headers, no magic strings (use `constants.py`), platform-neutral core. State clearly what you could not test.

**Before ending a session:** update `ai_docs/memory.md` and this file so the next session starts current.
