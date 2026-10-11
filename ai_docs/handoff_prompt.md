# Handoff prompt

Paste this (or point a new session at this file) to resume work.

---

You are continuing work on **dq_transcribe**, a local-first audio recording and transcription app, in the private repo `mizraith/dq_transcribe`.

**Read first:** `ai_docs/product_plan.md` (what the app is for: capturing swim-meet DQ radio calls, the four components, DQ record and state machine, roadmap), `ai_docs/guidelines.md` (coding standards and rules) and `ai_docs/memory.md` (facts, decisions, open items).

**Current state:** a working capture-and-queue app: browser capture UI with Start/Stop and a blinking REC light (`web/app.html`, `app.js`, `capture_worklet.js`), stdlib server (`server.py`), SQLite store (`database.py`), turn splitting (`audio_analysis.py`), whisper.cpp transcriber (`transcriber.py`), worker thread (`worker.py`), conversation grouping (`grouping.py`). Verified on the tablet end to end. Unit tests: `PYTHONPATH=src:tests python3 -m unittest discover -s tests`. Not yet tested: real FRS audio, sessions of hours, thresholds tuning.

**Environment:** the owner works from a Lenovo Idea Tab (Android 16, 8 GB RAM) with the Google Play build of Termux. There is no Linux container, and Termux:API is not used. You work in a cloud workspace and cannot connect to the tablet directly. The owner does not want to copy and paste code or commands.

**Running things on the tablet (the relay):** write a shell script, then run `COMMIT_TRAILERS="<trailers>" bash scripts/run_on_device.sh path/to/task.sh [wait_seconds]`. It commits the script to `device_tasks/` on `main`, and the tablet's `scripts/device_agent.sh` (which the owner starts once in Termux and leaves running) pulls it, runs it from the repo root, and publishes the output as a report on the `device-reports` branch. The helper prints the report. Round trips take roughly 15 to 40 seconds. If no report arrives, the agent is probably stopped: ask the owner to run `bash ~/dq_transcribe/scripts/device_agent.sh`. Start with read-only probe scripts. Tasks run unattended with the owner's permissions, so keep them small and non-destructive.

**Next steps (confirm with the owner before building):**
1. Owner records 2-3 hours of FRS audio (target Friday 2026-10-16). Afterward, inspect clips, thresholds (`SILENCE_DBFS`, `TURN_GAP_SECONDS`, capture start/end levels) and transcript quality using the stored raw data.
2. Re-measure whisper speed repeatably; compare `tiny`, `base`, `small`.
3. Consider a persistent whisper server, better turn detection, and a Windows backend.

**Standards reminder:** readable names, full docstrings and file headers, no magic strings (use `constants.py`), platform-neutral core. State clearly what you could not test.

**Before ending a session:** update `ai_docs/memory.md` and this file so the next session starts current.
