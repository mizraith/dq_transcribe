# Project memory

Facts and decisions to carry across sessions. Update this file as things change; keep stated facts separate from proposals.

## Stated by the owner

- Goal: an app that records audio from the microphone, transcribes it, and saves results in an editable lightweight local database. Must be savable, deployable, and shareable with others.
- Local processing is preferred wherever possible.
- Runs on a tablet. Keep the core generic in case it later runs on Windows.
- Owner is a Python fan and prefers Python.
- Repo: `mizraith/dq_transcribe` (private). Termux project name: `dq_transcribe`.
- Device: Lenovo Idea Tab, model T8336FU, MediaTek Dimensity 6300, 8 GB RAM, 223 GB storage, Android 16. Nothing else runs on it.
- The device has no Linux development environment option (checked Settings and Developer options), and it is not ChromeOS. Termux is installed.
- Termux is the Google Play build (version string `googleplay 2026.10.09`).
- Owner is new to Android/ChromeOS app development.
- The owner does not want to copy and paste code or commands on the tablet, and ideally wants Claude to work on it fully unattended. The clone lives at `~/dq_transcribe` in Termux. GitHub login in Termux is via `gh auth login`.
- The owner rejected running Claude Code inside Termux as a "barely working hack" (it is unsupported on Android), and has a Mac available as a possible development machine later.

## Decisions made (by assistant, with the owner's go-ahead on the overall approach)

- Microphone capture happens in Chrome (browser `MediaRecorder`), not through Termux:API. Reason: Termux:API is not published on Google Play and F-Droid's copy has a different signing key than the Play build of Termux. Chrome allows mic access on `localhost`. This is also portable to Windows.
- The Python side is a standard-library HTTP server (`src/dq_transcribe/server.py`) that serves pages and saves uploads to `~/.dq_transcribe/recordings/`. No third-party dependencies yet, on purpose: some pip packages need compilers and are painful in Termux.
- Browsers upload `webm` or similar; later steps must convert to 16 kHz mono WAV (ffmpeg is installed by the setup script).

- Remote execution on the tablet uses a GitHub relay, since the cloud workspace cannot connect to the tablet: the assistant queues a script with `scripts/run_on_device.sh`; `scripts/device_agent.sh` (running in Termux) pulls it, runs it in the repo folder, and pushes the output to the `device-reports` branch. Verified only in a local simulation (`tests/test_device_relay.sh`); not yet run on the tablet. The agent runs whatever is on `main` in `device_tasks/`, so the repo must stay private. Verified on the tablet 2026-10-10: the agent runs tasks and returns reports (about 15 to 40 s round trip).
- whisper.cpp is built on the tablet at `~/.dq_transcribe/whisper.cpp` (CLI `build/bin/whisper-cli`, which needs `LD_LIBRARY_PATH` set to `build/bin`), with the `ggml-base.bin` model in its `models/` folder. Build took about 4 minutes including the 141 MB model download. Set via `-m <model> -f <wav> -t 4 -l en -nt`.
- Verified on the tablet: Chrome mic recording works at `http://localhost:8000` (browser saves 48 kHz mono Opus in a `.webm`; ffmpeg converts it to 16 kHz mono WAV). Transcription of the owner's test clip ("test" repeated) was correct.
- Environment verified by probe: Python 3.13, git, gh, ffmpeg, clang, cmake and make installed; 8 cores; about 3 GB RAM available; 207 GB free; the project's unit tests pass on the tablet.

## Proposed, not yet confirmed

- SQLite for storage; a local web UI for viewing and editing notes.

## Open items

- Does Android keep Termux and the device agent alive for long periods, with the screen off or Chrome in the background (wake lock; Termux battery setting Unrestricted)? Only short sessions tested so far.
- Whisper `base` speed was inconsistent: about 6 s for an 11 s clip, but 15.6 s for a 5 s clip. Re-measure under repeatable conditions (idle device, repeated runs), and compare `tiny` and `small`.
- Whether recording continues with the screen off or Chrome in the background.

## Architecture (as of 2026-10-10)

- Browser captures mic (AudioWorklet, energy VAD, pre-roll, 16 kHz mono WAV) and uploads clips to `/api/clips`; clips queue in SQLite and a worker thread splits each into turns at pauses (>= 0.8 s below -45 dBFS) and runs whisper.cpp per turn.
- Clips are stored under `recordings/YYYY-MM-DD/` (owner request: group by day). `audio_filename` in the DB is the path relative to `recordings/`.
- Conversation groups are computed on the fly from clip times (gap < 5 s => same group), so retuning needs no reprocessing.
- Raw tuning data is kept: levels, pauses, analysis params, capture info, whisper JSON.
- Stability measures for long sessions: unlimited upload retry (only 4xx drops a clip), audio-context resume, mic-disconnect and pipeline-stall warnings, wake-lock re-acquire. Long silences are expected (owner), so silence never warns; instead the page shows "Last audio received: HH:MM:SS (N s ago)" so a watcher can tell silence from a dead mic.

## Status log

- 2026-10-10: Repo scaffolded; Termux environment set up on the tablet; browser mic-test slice written and unit-tested in the cloud workspace. Not yet run on the tablet.
- 2026-10-10: Device relay (agent + run_on_device) built and passed a local simulated end-to-end test. Waiting for the owner to start the agent on the tablet.
- 2026-10-10: Agent started on the tablet. Mic test passed, whisper.cpp built, first transcription verified. Next: wire recording, conversion, transcription and SQLite storage into the app.
- 2026-10-10: Capture app built, 23 unit tests pass, deployed and verified on the tablet with JFK samples (2-turn clip split correctly; ~0.4x real time with `base`). Owner plans a 2-3 hour recording session on Friday 2026-10-16 to gather real FRS audio. Test data was cleared afterward.
- 2026-10-10: Capture settings are touch sliders (no typing; limits in constants.py). Added the "last audio received" status line. Owner will run a test in the next few days (before the Friday 2026-10-16 long session).
- 2026-10-10: Owner described the product (swim-meet DQ capture -> detection -> review -> publication/protests). Captured in `ai_docs/product_plan.md`, with proposals and open questions marked.
- 2026-10-10: Owner answered plan questions: local models (even an LLM) OK if shipped with the app, no online AI, pluggable models; anyone in the chain can decline, benefit of the doubt to the swimmer; protest window starts at Notification, typically 30 min. Plan updated.
- 2026-10-10: Stored the 2026 USA Swimming rulebook in `rulebook/` (downloaded via the tablet; cloud shell cannot reach usaswimming.org). Owner chose llama.cpp as local LLM runtime, to be part of install on Android/ChromeOS/Windows/Mac. Admin fills missing E/H/L and description quickly; each call gets a link icon -> transcript popup with audio play.
- 2026-10-10: Required to publish: E/H/L, swimmer name, club, official, referee, description (code optional but wanted). Default sort E/H/L. Install uses built-in tools per platform (ChromeOS Linux, Mac Terminal, Windows PowerShell).
- 2026-10-10: Windows target is WSL only (owner hates PowerShell); Mac uses Terminal. Swimmer name/club will come from the Hy-Tek Meet Manager file by E/H/L; files can update mid-meet, so the main window needs browse/load-new-file. Owner is getting Friday's file.
- 2026-10-10: Meet structure: meet (date+name id) -> days (1-5) -> sessions (1-3/day, ~4 h, <8). Meet Manager file loaded via file picker or URL; usually arrives on a USB thumb drive from Windows.
- 2026-10-10: Event numbers unique per meet (rare conflicts get a letter, e.g. 2b). Relay DQs record the leg (1st-4th) and relay name club-letter (PASA-A) instead of swimmer name.
- 2026-10-10: Declined -> marked for deletion, human confirms, goes to trash bin (recover/permanent delete). Overturned published DQs never deleted. "Notified by" drop-down (people + SMS Push / HTML Publish / None Required). Corrections: fix and republish; confused calls get declined. Owner wants Claude to keep asking clarifying questions.
- 2026-10-10: Republish restarts the 30-min protest window on re-notify; one admin on one tablet (no logins for now); Overturned can be reopened by a further protest; officials roster typed per meet.
- 2026-10-10: A DQ can have several infractions; admin enters protests and rulings; trash emptied only by admin after the meet; protest-cycle limit undecided (setting, default 2).
- 2026-10-10: Radio audio comes by cable from the radio (not built-in mic), one channel, wording varies a lot. Admin can publish without referee acceptance. Added clipping ("TOO LOUD") indicator to capture page for cable level setting.
- 2026-10-10: Protest clock = 30 min from the race (rulebook 102.22.4), not notification. LLM: measure sizes first. Unclear calls: owner flagged that linking call fragments to DQs needs a real workflow design (no choice yet). First output: list by event/heat/lane.
- 2026-10-10: Republish does not reset the deadline (30 min from race stands). Late protests can be accepted by referee/admin-with-permission for extenuating circumstances; window must be overridable.
- 2026-10-10: Official roles: Judge, Chief Judge, Referee, RTO, Starter. Protest limit 2 (Deck Ref then Meet Ref). SMS later (hosted sign-up + push). Owner asked to be reminded: send DQ slip photo; do radio-cable dry run.
- 2026-10-10: DQs go into Meet Manager by hand from a clean per-event summary after event close (never touch MM DB). Publish full name + club (standard), coach-only thin wall during meet, taken down after; only coaches notified. Archive >= 1 year as zip for meet host. 12-hour time (now applied in UI and transcript).
- 2026-10-10: Admin closes an event (often before protest window ends); needs quick single-event view and fast single-DQ edit. Coach access: one meet password, tablet serves page on local network with QR code; password rotation later.
- 2026-10-10: Added `scripts/start_dq.sh` (one command: wake lock, git pull, agent, server restart, open Chrome); shortcut `dq_transcribe` via symlink in $PREFIX/bin. Owner granted Termux all-files access (useful for loading Meet Manager files and saving archives).
- 2026-10-10: Operator reviews/enters DQs in a separate Chrome tab while the capture tab keeps running (background-tab throttling to test in dry run). Start script and `dq_transcribe` shortcut verified on the tablet; agent link restored.
- 2026-10-10 23:07: Pause point. All work committed and pushed. Next session: remind owner (DQ slip photo, radio-cable dry run), then follow handoff next steps.
- 2026-10-12: Owner sent DQ slip photos (rev. 7/19 and 1/24). Transcribed into reference/dq_codes CSVs with old->new mapping; photos in reference/dq_slips. Slip has START/SWIM/TURN/FINISH phase boxes (to capture), turn/stroke/swimmer detail blanks, CJ initials. IM stroke detail is redundant per owner. Relay 6A-D/6F-H mapping is assumed.
- 2026-10-12: Added clip trash bin (trash icon per clip; Trash view with Restore and two-tap Delete forever; trashed queued clips are skipped) and an Audio input picker (remembered by id and name; capture info records inputLabel). Owner wants the tablet's audio jack as the input.
- 2026-10-12: DQ codes can vary by meet; latest slip normally used (per-meet revision setting). Relay letter codes not used; track relay infraction + swimmer number. Phases are multi-select memory aids; infraction unchanged.
- 2026-10-14: UI rework per owner: left control column (~1/4 width: input, level check, start/stop, meter, settings, Trash view, downloads), transcript on the right; "Check levels" live meter without recording; trash and delete need an inline confirmation (survives polling); list no longer redraws while audio plays or when unchanged.
- 2026-10-14: Transcription: whisper initial prompt from `src/dq_transcribe/data/whisper_prompt.txt` (no digits: example numbers leaked into transcripts), `-sns` suppresses [Music]/[Gunshot] labels, leftover bracket/asterisk tags stripped; pre-roll raised to 1.0 s ("DQ" was being cut to "Q"). Observed on real audio: "heat" heard as "8", "lane" as "9" without prompt. Downloaded ggml-small.en to the tablet for comparison.
- 2026-10-14: Model comparison on real clips (with prompt): base ~0.3-0.4x real time, small.en ~1x real time but noticeably more accurate ("Possible DQ", "lane six", "two butterfly kicks"). Base kept as default pending owner choice; all audio is kept so clips can be reprocessed with small.en later.
- 2026-10-14: Two-pass transcription built (base draft, small.en refine in parallel, refine keeps hand edits and stores refined_text). Measured: whisper-cli model load costs ~3 s (base) / ~10 s (small.en) per call, so per-turn reloads dominated. Switched to persistent whisper-server processes (ports 8178 draft, 8179 refine; refine at nice 10), with leftover-server cleanup, SIGTERM shutdown, and whisper-cli fallback. Owner asked to be told before any long-running tablet task.
