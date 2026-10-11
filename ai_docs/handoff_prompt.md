# Handoff prompt

Paste this (or point a new session at this file) to resume work.

---

You are continuing work on **dq_transcribe**, a local-first audio recording and transcription app, in the private repo `mizraith/dq_transcribe`.

**Read first:** `ai_docs/product_plan.md` (what the app is for: capturing swim-meet DQ radio calls, the four components, DQ record and state machine, roadmap), `ai_docs/guidelines.md` (coding standards and rules) and `ai_docs/memory.md` (facts, decisions, open items).

**Current state (2026-10-10 pause point):** component 1 of 4 is built: a working capture-and-queue app.
- **Capture page** (`web/app.html`, `app.js`, `capture_worklet.js`): Start/Stop with a blinking REC light, a level meter with a TOO LOUD clipping warning, touch sliders for capture settings, "Last audio received" time, a 12-hour clock, and uploads that never drop a clip.
- **Server and pipeline:** stdlib `server.py`; SQLite `database.py`; turn splitting in `audio_analysis.py`; whisper.cpp in `transcriber.py`; a worker thread in `worker.py`; call/response grouping in `grouping.py` (gap < 5 s). Clips are stored in per-day folders.
- **Tests and tablet:** verified on the tablet end to end with sample audio. Unit tests: `PYTHONPATH=src:tests python3 -m unittest discover -s tests` (23 pass).
- **Start command:** `dq_transcribe` in Termux (`scripts/start_dq.sh`) starts the wake lock, git pull, device agent and server, and opens Chrome. Verified.
- **Rulebook:** the 2026 USA Swimming rulebook is in `rulebook/`, with dated names and a README.
- **Product design:** captured in detail in `ai_docs/product_plan.md`, covering DQ fields, states, protests, meets/sessions, publication, archive and install. Only two open questions remain there.
- **Not yet tested:** real FRS audio over the radio cable, multi-hour sessions, a background capture tab while reviewing in another tab, and threshold tuning.

**Environment:** the owner works from a Lenovo Idea Tab (Android 16, 8 GB RAM) with the Google Play build of Termux. There is no Linux container, and Termux:API is not used. Termux has all-files access (`~/storage/...`). You work in a cloud workspace and cannot connect to the tablet directly. The owner does not want to copy and paste code or commands.

**Running things on the tablet (the relay):** write a shell script, then run `COMMIT_TRAILERS="<trailers>" bash scripts/run_on_device.sh path/to/task.sh [wait_seconds]`. It commits the script to `device_tasks/` on `main`, and the tablet's `scripts/device_agent.sh` (which the owner starts once in Termux and leaves running) pulls it, runs it from the repo root, and publishes the output as a report on the `device-reports` branch. The helper prints the report. Round trips take roughly 15 to 40 seconds. If no report arrives, the agent is probably stopped: ask the owner to type `dq_transcribe` in Termux (shortcut for `scripts/start_dq.sh`, which starts the agent, the server and Chrome). Start with read-only probe scripts. Tasks run unattended with the owner's permissions, so keep them small and non-destructive.

**Remind the owner first (he asked for these reminders):** (1) send a photo of a current DQ slip; (2) do the radio-cable dry run before Friday 2026-10-16 (volume via the TOO LOUD indicator, sliders, USB-C adapter as Chrome's mic). See `ai_docs/product_plan.md` section 9b.

**Next steps (confirm with the owner before building):**
1. Owner records 2-3 hours of FRS audio (Friday 2026-10-16), with the event/heat/lane of every DQ as ground truth. Afterward: inspect clips, tune thresholds (`SILENCE_DBFS`, `TURN_GAP_SECONDS`, capture levels), and judge transcript quality using the stored raw data.
2. Import the DQ slip codes and descriptions (from the owner's photo) as versioned reference data.
3. Design the DQ data model (meet → day → session; DQ with several infractions; append-only state history) and the touch-friendly call-linking workflow.
4. Measure whisper speed repeatably (`tiny`, `base`, `small`), and benchmark llama.cpp model sizes on the Friday audio.
5. Inspect the Hy-Tek Meet Manager file format once the owner provides Friday's file.

**Standards reminder:** readable names, full docstrings and file headers, no magic strings (use `constants.py`), platform-neutral core. State clearly what you could not test.

**Before ending a session:** update `ai_docs/memory.md` and this file so the next session starts current.
