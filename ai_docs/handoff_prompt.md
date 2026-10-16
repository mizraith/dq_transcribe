# Handoff prompt

Paste this (or point a new session at this file) to resume work on dq_transcribe.
For the separate Officials Sign-In app, use `ai_docs/officials_signin_handoff.md` instead.

---

You are continuing work on **dq_transcribe**, part of the owner's *Swimming_Admin_Assistant*
project, in the private repo `mizraith/dq_transcribe`. It records FRS radio calls between swim
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
- Tests: `PYTHONPATH=src:tests python3 -m unittest discover -s tests` (all pass). Keep new test
  methods inside their class, above the `__main__` guard.

**Not verified yet:** the Meet Manager database reader against a real file (table names are
from documentation); real PDF/HTML heat sheets (parser written from Hy-Tek's usual layout);
radio audio through an attenuator; multi-hour capture (Friday 2026-10-16).

**Next (owner's order):** check the owner's real Meet Manager files (database, PDF, HTML) and
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
