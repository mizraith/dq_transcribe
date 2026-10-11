# dq_transcribe

Local-first audio recording and transcription. Records from the device
microphone, transcribes on-device, and keeps results in an editable local
database. Nothing leaves the device.

**Status:** capture-and-queue app working on the tablet. Open the page, tap
**Start capturing**, and audio is cut into clips, transcribed turn by turn, grouped
into call/response conversations, and stored in an editable local database.

## Run it (Termux)

```bash
bash scripts/termux_setup.sh                 # once
PYTHONPATH=src python -m dq_transcribe       # start the server
```

Open <http://localhost:8000> in Chrome, tap **Start capturing**, and allow the
microphone. A blinking red light shows that capture is on. Keep Chrome in the
foreground with the screen on (the page requests a screen wake lock).

- Clips are saved as WAV files in one folder per day: `~/.dq_transcribe/recordings/YYYY-MM-DD/`.
- Everything else (clips, turns, transcripts, loudness data, edits) is in the SQLite file `~/.dq_transcribe/notes.db`.
- Clips less than 5 seconds apart are grouped as one conversation (`CONVERSATION_GAP_SECONDS`).
- The page shows "Last audio received: HH:MM:SS" so you can tell a quiet radio from a dead microphone.
- Uploads are never dropped when the server is unreachable; they retry until sent.
- The page `/mic-test` is the original microphone check.

Run the tests with `PYTHONPATH=src:tests python3 -m unittest discover -s tests`.

## Device agent (lets an AI assistant run commands on the tablet)

In Termux, start it once and leave it running:

```bash
bash ~/dq_transcribe/scripts/device_agent.sh
```

It polls this repo, runs scripts that appear in `device_tasks/`, and pushes the
output to the `device-reports` branch. See the safety note at the top of
`scripts/device_agent.sh`: it executes whatever is committed to `main`, so keep
the repo private. Test the relay itself with `bash tests/test_device_relay.sh`.

## Target platform

- Primary: Lenovo Idea Tab (Android 16) running Python inside Termux.
- Later: Windows. The core stays platform-neutral to make that possible.

## Layout

| Path | Purpose |
| --- | --- |
| `src/dq_transcribe/` | Application package (`constants.py` holds all shared strings and settings) |
| `tests/` | Automated tests |
| `scripts/` | Setup, the tablet device agent, and the assistant's `run_on_device.sh` |
| `device_tasks/` | Scripts queued to run on the tablet (one-shot, timestamped) |
| `build/`, `dist/` | Build output; contents are git-ignored |
| `ai_docs/` | Guidelines, project memory, and the AI handoff prompt |

## For AI assistants

Start with `ai_docs/handoff_prompt.md`, then read `ai_docs/guidelines.md` and
`ai_docs/memory.md`.
