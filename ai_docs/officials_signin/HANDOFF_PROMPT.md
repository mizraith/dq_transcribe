# Officials Sign-In: handoff prompt

Point a new AI session at this file (or paste it) to pick up work on **Officials
Sign-In** and its **Coaches Sign-In** page. Then read `GUIDELINES.md` (rules) and
`MEMORY.md` (decisions, gotchas, open items) in this folder before changing anything.

---

You are continuing work on **officials_signin**, the second app in the owner's
*Swimming_Admin_Assistant* project, in the private repo `mizraith/dq_transcribe` (one repo,
two apps; the first is **dq_transcribe**, the DQ recorder, worked on by another chat).
The owner is **Red**; see `GUIDELINES.md` for how he works and what he expects.

## What the app does

A local-first, touch-first **sign-in desk** for swim meet officials (and coaches) on an
Android tablet (Termux runs the server, Chrome shows the pages). Server on port **8010**,
data in `~/.officials_signin/` (SQLite), stdlib Python only.

- **Admin Assistant main page** (`/`): launcher for the suite's apps (DQ Transcribe on
  port 8000, Officials, Coaches), the current meet, the meets list (open, archive,
  delete archived, zip), Meet setup and the demo meet. The one current meet and session
  is shared by every app; DQ reads it from `/api/suite/current`.
- **Officials** (`/officials`): sign in per session by **camera** (reads the USA Swimming app's
  Membership card with in-browser OCR, Tesseract.js bundled in `web/vendor`) or by name;
  the card check (good standing, background check, athlete protection) validates them,
  otherwise the admin taps **Looks good**. Edit / Remove per row. LSC drop-down (59
  LSCs, default Pacific Swimming) and club box for when OCR fails.
- **Teams** for stroke & turn judges: equal seniority blocks, 4 or 3 teams, ACJ / 15 m /
  Relief off the teams, trainees with mentors, Team Lead stars, drag and drop (swap,
  move, reorder), jurisdiction box with flip, fixed or rotating ends with a rotation
  schedule. Only **checked** officials go on teams; **corner officials** never do.
- **Printouts**: session summary, meet summary, team page (also a full-screen display
  for phone photos); **Save meet (zip)** with pages, CSV and rosters, never member IDs.
- **Meets** and **Meet setup** (sessions as table rows) on the main page; **demo meet**
  in its own database (per browser, cookie), with made-up officials and coaches;
  per-session sizes.
- **Coaches** (`/coaches`, teal): same desk without teams; Head coach toggle (any number
  per club); opens in its own tab. All pages follow one meet and session.
- **Roster for dq_transcribe**: `/roster.json` (contract in
  `ai_docs/officials_roster_format.md`).

## Where things are

- `src/officials_signin/`: `server.py` (routes, `build_web_config`), `database.py`,
  `constants.py`, `card_reader.py` (OCR text to card fields, votes, checks), `teams.py`,
  `reports.py` (printouts), `export.py` (meet zip), `demo.py`, `coaches.py` (coaches
  page: its tables, API and pages, plugged in via `server._coaches_module`),
  `roster.py`, `__main__.py` (start, self-restart on code changes).
- `src/officials_signin/web/`: `home.html/js` + `meets.js` (main page), `signin.html/js`
  (officials), `coaches.html/js`,
  `desk.css`, `card_camera.js`, `desk_shared.js`, `card_scanner.js`, `print.css`,
  `demo.html`, `vendor/tesseract/`.
- `tests/officials_signin/`: unit and HTTP tests (run as in `GUIDELINES.md`).
- `scripts/start_signin.sh` (`officials_signup` on the tablet; opens `/officials` and
  `/coaches`), `scripts/start_admin_assistant.sh` (`admin_assistant`: starts both
  servers, opens only the main page).
- `DQ_SUITE_HANDOFF.md`: what the DQ Transcribe chat must change to join the suite.

## State (2026-10-16, 08:40)

The Admin Assistant main page, the suite API and the shared top bar are built, tested
and pushed (commit 3342e3c). The tablet still runs the previous code until it pulls
(the owner is asked first: the server restarts itself on pull). Today's meet is set up
on the tablet: "All Treats No Tricks Candy Meet Block Party", Friday PM, 4:45 PM,
officials meeting 3:45 PM.

## Next

1. With the owner's OK: update the tablet, then import DQ's "10/14 Test" (2026-10-14)
   into the suite's meets through the app API (one session needed).
2. The DQ Transcribe chat works from `DQ_SUITE_HANDOFF.md`; answer its questions.
3. The owner's feedback from the Candy Meet.
4. Open items at the end of `MEMORY.md` (coach card requirements, Team Lead rule, ...).
5. Before every pause, update `MEMORY.md` (newest decision first), this file's State and
   Next, and `GUIDELINES.md` if a standing rule changed; then commit and push.
