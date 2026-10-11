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
- The owner does not want to copy and paste code on the tablet. The clone lives at `~/dq_transcribe` in Termux; updates arrive with `git pull`. GitHub login in Termux is via `gh auth login`.

## Decisions made (by assistant, with the owner's go-ahead on the overall approach)

- Microphone capture happens in Chrome (browser `MediaRecorder`), not through Termux:API. Reason: Termux:API is not published on Google Play and F-Droid's copy has a different signing key than the Play build of Termux. Chrome allows mic access on `localhost`. This is also portable to Windows.
- The Python side is a standard-library HTTP server (`src/dq_transcribe/server.py`) that serves pages and saves uploads to `~/.dq_transcribe/recordings/`. No third-party dependencies yet, on purpose: some pip packages need compilers and are painful in Termux.
- Browsers upload `webm` or similar; later steps must convert to 16 kHz mono WAV (ffmpeg is installed by the setup script).

## Proposed, not yet confirmed

- Transcription with whisper.cpp built in Termux (faster-whisper has no Android build); start with the `base` model and measure.
- SQLite for storage; a local web UI for viewing and editing notes.

## Open items

- Does the Chrome mic test page work on the tablet (permission prompt, file saved)?
- Whisper model size versus speed on the Dimensity 6300.
- Whether recording continues with the screen off or Chrome in the background.

## Status log

- 2026-10-10: Repo scaffolded; Termux environment set up on the tablet; browser mic-test slice written and unit-tested in the cloud workspace. Not yet run on the tablet.
