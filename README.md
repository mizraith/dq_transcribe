# dq_transcribe

Local-first audio recording and transcription. Records from the device
microphone, transcribes on-device, and keeps results in an editable local
database. Nothing leaves the device.

**Status:** working on the tablet end to end: capture radio calls, transcribe them,
detect DQ calls (with likely slip codes), manage DQs (filter, group by event,
notify, protests, printable slips), load the Hy-Tek Meet Manager file (swimmer and
club fill in from event/heat/lane), and archive a meet as a zip. See
`ai_docs/product_plan.md` for the full design and `ai_docs/handoff_prompt.md` for
the current state.

## Run it (Termux)

One command starts everything (wake lock, code update, device agent, app server)
and opens the app in Chrome:

```bash
bash ~/dq_transcribe/scripts/start_dq.sh
```

To make it a short command, run this once:
`ln -sf ~/dq_transcribe/scripts/start_dq.sh "$PREFIX/bin/dq_transcribe"`.
Then type `dq_transcribe` (or `dq_transcribe stop`, `dq_transcribe status`).

First-time setup and the manual way:

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
- **Audio input:** pick the microphone, headset jack or USB audio adapter from the list above the Start button. The choice is remembered.
- **Layout:** controls on the left (input, level check, start/stop, meter, settings, Trash, downloads); transcript on the right.
- **Check levels:** shows the live meter without recording anything, so levels can be set before capturing.
- **Trash:** each clip has a trash icon, which asks for confirmation. The Trash view (left column) can restore a clip or delete it for good (also confirmed).
- **Transcription vocabulary:** whisper is primed with swim-meet words from `src/dq_transcribe/data/whisper_prompt.txt`. Keep numbers out of it; whisper copies them into transcripts.
- **Meet setup** (left column): officials roster, **Meet file** (Hy-Tek backup .zip/.mdb, PDF or HTML report; needs `pkg install poppler mdbtools` in Termux), and **End of meet** (archive zip, close meet, empty trash).
- **DQs view:** status filter, **Group by event** with Notify event, protests, and **Print slip** / event slips.
- **+ DQ** beside each transcript line makes a DQ by hand from that line (or the words selected in it).
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

Start with `ai_docs/handoff_prompt.md` and `ai_docs/product_plan.md`, then read `ai_docs/guidelines.md` and
`ai_docs/memory.md`.
