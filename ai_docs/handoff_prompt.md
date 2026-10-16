# Handoff prompt

Paste this (or point a new session at this file) to resume work on dq_transcribe.
For the separate Officials Sign-In app, use `ai_docs/officials_signin/HANDOFF_PROMPT.md` instead.

---

You are continuing work on **DQ Transcribe** (package and command `dq_transcribe`), a sub-app of
the owner's **Admin Assistant** suite (claude.ai project *Swimming_Admin_Assistant*), in the
private repo `mizraith/dq_transcribe`. It records FRS radio calls between swim
officials on a tablet, transcribes them locally, finds DQ calls, and manages DQs through
notification and protests.

**Read first:** `ai_docs/product_plan.md` (purpose, components, DQ states, design rule:
automate first, fewest taps), `ai_docs/guidelines.md` (standards, safety) and
`ai_docs/memory.md` (dated decisions and facts; newest at the bottom).

**State on 2026-10-15 (all installed on the tablet):**
- **Capture and transcription:** AudioWorklet capture with level check and too-loud warning;
  two-pass whisper (base draft on whisper-server :8178, small.en refine :8179); clips grouped
  into conversations; meets with per-meet folders.
- **Call detection:** `call_parser.py` (rule-based, one candidate per lane) +
  `data/infraction_phrases.csv` + `slip_codes.py` (ranks every slip line against what was
  heard). Event stroke comes from the Meet Manager file when loaded, else learned from calls/DQs.
- **DQs:** `dq_store.py`; states called / accepted / notified / protested / upheld /
  overturned / declined; list status splits accepted into Incomplete / Pending notification;
  filter bar + Group by event with readiness and **Notify event**; protest window = 30 min
  from the call; late/extra protests need a reason. One-tap likely slip codes (with stroke tags).
  **+ DQ** on any transcript line. Printable slip (`slip_page.py`, `web/dq_slip.html`, bundled
  OFL script font) at `/slips?ids=` or `?event=`.
- **Meet setup view** (`web/meet_view.js`): name/date, officials roster (auto-add), **Meet file**
  (Hy-Tek database .zip/.mdb via mdbtools, PDF via pdftotext, HTML, text; `meet_files/`
  package, versioned, newest active; fills swimmer/club, event labels, strokes), **End of meet**
  (archive zip without Meet Manager files, close/reopen, empty trash only after close).
- Also: DQ trash (swipe left, restorable), transcript lines show their DQs, **Import officials**
  from the Sign-In app (`officials_roster.py`), view tabs at the top, and a workflow demo meet
  (`python -m dq_transcribe.demo_data`).
- Tests: `PYTHONPATH=src:tests python3 -m unittest discover -s tests` (all pass). Keep new test
  methods inside their class, above the `__main__` guard.

**State on 2026-10-16 (installed on the tablet): Admin Assistant suite.** See
`ai_docs/officials_signin/DQ_SUITE_HANDOFF.md` (owned by the Officials Sign-In chat; do not edit
`src/officials_signin/**`, `scripts/start_signin.sh`, `scripts/start_admin_assistant.sh` or
`ai_docs/officials_signin/**`). The main page and the current meet/session live on the
Officials Sign-In server (:8010, `/api/suite/current`, `/select`, `/meets`). DQ's page has the
suite top bar (☰, DQ Transcribe, meet, session drop-down, Transcript/DQs/Trash) and ☰ menu
(Meets & Main Page, Downloads, DQ meet setup, Mic test, Admin Assistant ›). DQ follows the
suite's meet (`POST /api/suite-link`; `meets.suite_meet_id`); capture records to the meet and
session fixed at Start until Stop. Automatic DQs (`auto_dq.py`), the coach page on the Wi-Fi
(`coach_server.py`, :8020), printout requests, transcript workflow filter (Processing /
Transcribed / DQ made / Needs you), event DQ summary (`/event-summary`; `?all=1` = every
status, for the suite's Reports) are all in `ai_docs/memory.md`.

**Not verified yet:** the Meet Manager database reader against a real file (table names are
from documentation); real PDF/HTML heat sheets (parser written from Hy-Tek's usual layout);
radio audio through an attenuator; multi-hour capture (Friday 2026-10-16).

**Next steps added 2026-10-16 (owner):**
1. **Move to a new, renamed repository** for the Admin Assistant suite (the repo now holds
   more than dq_transcribe). Plan it with the owner and the Officials Sign-In chat: new name,
   `git` history kept (push the whole history to the new remote), the tablet's clone and
   device agent re-pointed, `scripts/*` paths and `REPO_DIRECTORY` in `start_dq.sh` updated,
   docs links updated. Do it between meets, never on a meet day.
2. **Owner clones the repo locally** to review the code, layout and file names (WSL on
   Windows, not PowerShell): `git clone https://github.com/mizraith/dq_transcribe.git` (or the new
   name after step 1), then read `README.md`, `ai_docs/` and `src/`. Collect naming/layout
   changes as a list for the assistant.
3. **Packaging** (product_plan 9a and 9b step 7): per-platform install scripts, pinned engines,
   model checksums, health check, one start command for the whole suite.
4. **Icon** for the Admin Assistant (favicon, web app manifest / home-screen icon, QR sign).
5. **Test on a Mac** with the built-in Terminal: tests, capture, both whisper passes, coach page,
   printing. Write down what had to change.

**Release:** `v0.2.0-alpha` (version 0.2.0a1, tagged 2026-10-16) is the ALPHA of the suite with
DQ Transcribe, installed on the tablet for the Candy Meet. Bump `__version__` and
`pyproject.toml` together; tag releases as `vX.Y.Z-<stage>`.

**Next (owner's order, before 2026-10-16):** check the owner's real Meet Manager files (database, PDF, HTML) and
fix the importers; then regrouping turns between conversations (per-utterance group override,
drag plus one-tap up/down) and merge/split DQs; then sessions (from the Meet Manager data if
present). After Friday: offline replay-and-score harness on the recorded audio.

**Environment:** tablet = Lenovo Idea Tab, Android 16, Termux (Google Play build, all-files
access, no Termux:API), Chrome at http://localhost:8000. The owner does not copy and paste:
deliver by committing, and run things on the tablet with the relay:
`COMMIT_TRAILERS="<trailers>" bash scripts/run_on_device.sh path/to/task.sh [wait_seconds]`
(the tablet's agent runs `device_tasks/` scripts, 600 s limit, and pushes reports to the
`device-reports` branch). Tell the owner before long-running tablet tasks, and ask before
restarting the app unless he has said to install as you go. Keep tasks small and
non-destructive; never touch credentials.

**Standards reminder:** readable names, full docstrings and file headers, no magic strings
(use `constants.py`), platform-neutral core, honest about what was not tested.

**Before ending a session:** update `ai_docs/memory.md` and this file.
