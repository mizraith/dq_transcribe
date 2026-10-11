# dq_transcribe

Local-first audio recording and transcription. Records from the device
microphone, transcribes on-device, and keeps results in an editable local
database. Nothing leaves the device.

**Status:** early. A local server and a microphone test page exist; transcription and storage are not built yet.

## Try the mic test (Termux)

```bash
bash scripts/termux_setup.sh                 # once
PYTHONPATH=src python -m dq_transcribe       # start the server
```

Then open <http://localhost:8000> in Chrome, tap **Record**, and allow the microphone.
Recordings are saved under `~/.dq_transcribe/recordings/`.

Run the tests with `PYTHONPATH=src python -m unittest discover -s tests`.

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
