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

- Remote execution on the tablet uses a GitHub relay, since the cloud workspace cannot connect to the tablet: the assistant queues a script with `scripts/run_on_device.sh`; `scripts/device_agent.sh` (running in Termux) pulls it, runs it in the repo folder, and pushes the output to the `device-reports` branch. Verified only in a local simulation (`tests/test_device_relay.sh`); not yet run on the tablet. The agent runs whatever is on `main` in `device_tasks/`, so the repo must stay private.

## Proposed, not yet confirmed

- Transcription with whisper.cpp built in Termux (faster-whisper has no Android build); start with the `base` model and measure.
- SQLite for storage; a local web UI for viewing and editing notes.

## Open items

- Is the device agent running on the tablet, and does Android keep Termux alive in the background (wake lock, battery set to Unrestricted)?
- Does the Chrome mic test page work on the tablet (permission prompt, file saved)?
- Whisper model size versus speed on the Dimensity 6300.
- Whether recording continues with the screen off or Chrome in the background.

## Status log

- 2026-10-10: Repo scaffolded; Termux environment set up on the tablet; browser mic-test slice written and unit-tested in the cloud workspace. Not yet run on the tablet.
- 2026-10-10: Device relay (agent + run_on_device) built and passed a local simulated end-to-end test. Waiting for the owner to start the agent on the tablet.
