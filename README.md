# dq_transcribe

Local-first audio recording and transcription. Records from the device
microphone, transcribes on-device, and keeps results in an editable local
database. Nothing leaves the device.

**Status:** project scaffold only. No application code yet.

## Target platform

- Primary: Lenovo Idea Tab (Android 16) running Python inside Termux.
- Later: Windows. The core stays platform-neutral to make that possible.

## Layout

| Path | Purpose |
| --- | --- |
| `src/dq_transcribe/` | Application package (`constants.py` holds all shared strings and settings) |
| `tests/` | Automated tests |
| `scripts/` | Setup and helper scripts (for example Termux setup) |
| `build/`, `dist/` | Build output; contents are git-ignored |
| `ai_docs/` | Guidelines, project memory, and the AI handoff prompt |

## For AI assistants

Start with `ai_docs/handoff_prompt.md`, then read `ai_docs/guidelines.md` and
`ai_docs/memory.md`.
