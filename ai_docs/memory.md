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
- Owner is new to Android/ChromeOS app development.
- The owner does not want to copy and paste code on the tablet.

## Proposed, not yet confirmed

- Python core with a small local web UI opened in Chrome at `localhost`.
- Transcription with whisper.cpp built in Termux (faster-whisper has no Android build); start with the `base` model and measure.
- Microphone capture through Termux:API (`termux-microphone-record`).
- SQLite for storage.

## Open items

- Where Termux and Termux:API were installed from (F-Droid or GitHub is required; the Play Store build is outdated).
- Whether `termux-microphone-record` works on this tablet.
- Whisper model size versus speed on the Dimensity 6300.
