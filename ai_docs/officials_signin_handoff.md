# Officials Sign-In: handoff and development prompt

Paste this whole file into a new Claude chat (or point the chat at this file in
the repo) to start building the **Officials Sign-In** app. It is the second app
in the owner's *Swimming_Admin_Assistant* project and is built **in parallel**
with dq_transcribe, which another chat is working on at the same time.

---

## Your role

You are building **officials_signin**, a local-first, touch-first app that runs
on a tablet at swim meets. Officials sign in at the start of each session; the
admin checks their credentials; later the admin builds team assignments; the app
publishes a **final officials listing** that the DQ app (dq_transcribe) imports.

The owner is **Red**: an expert Python developer, new to Android. He works from
the tablet and does **not** copy and paste code or commands. You deliver work by
committing to the repo, and you run things on the tablet through the GitHub
relay described below.

## Read first (in the repo `mizraith/dq_transcribe`)

- `ai_docs/guidelines.md`: coding standards and safety rules (they apply to you).
- `ai_docs/product_plan.md`, section **9c** ("Companion app: officials sign-in"):
  what the owner has said so far, plus proposals. Also section 1, the
  **automation-first design rule**.
- `README.md`, `scripts/start_dq.sh`, `scripts/device_agent.sh`,
  `scripts/run_on_device.sh`: how the existing app is started and how the relay works.
- `src/dq_transcribe/server.py`, `database.py`, `constants.py`, `web/app.html`:
  the house style for a stdlib server, SQLite storage, centralized constants, and
  a touch page served as a `string.Template`. Copy the patterns, not the code.

## The owner's standards (non-negotiable)

- Python first. Readable names, no cryptic abbreviations.
- An accurate, well-formatted **docstring for every module, class and function**,
  and a file header docstring on every file. Keep them in sync with the code.
- **No magic strings or numbers:** centralize them in the app's own `constants.py`.
- Platform-neutral core. Android/Termux today; Windows (WSL only, never
  PowerShell) and Mac later.
- **Automation first:** the deck is very busy. Keep taps to a minimum and make
  good guesses. A person is involved only when the app is at a loss or there is
  an exception. Judge every screen by how few taps the common case takes.
- Be honest about what you tested and what you could not (anything involving the
  camera can only be verified on the tablet).
- Tell the owner **before** starting any long-running task on the tablet, so he
  doesn't think you have gone offline. **Ask before restarting** anything on the tablet.
- End every commit message with the attribution trailers your session gives you.

## What the owner has said (2026-10-14)

- The tablet becomes the officials' **sign-in form** at the start of each session.
  It is a one-time workflow per session.
- **Validation today:** by eye. The admin looks at the official's printed card,
  or (preferred) the **USA Swimming app on the official's phone** while they are
  logged in. Owner's idea: a **reader that uses the tablet camera** to scan the
  credential. He is not sure USA Swimming's database can be queried (no public
  lookup service was found).
- **Collect:** name, role(s), **club, zone, years certified** (if possible).
- **Trainees** (formerly "apprentices") **must be paired** with a certified official.
- Usually sign-in covers **one session at a time**. At some meets officials
  **pre-sign up for later sessions that day**.
- **Team assignment rules:** to be discussed later. Ask the owner when you get there.
- It should be **its own app** that outputs a **final officials listing** for
  dq_transcribe to ingest.

## Design (confirmed with the owner 2026-10-15)

- **Same repo, separate app** in `src/officials_signin/` with its own server,
  port, database, web page, constants and start script. It shares no code or
  database with dq_transcribe, only the roster file format below.
- **Port 8010**; data in `~/.officials_signin/`.
- **Start script** `scripts/start_signin.sh` (start, stop, status; opens the
  browser). It never starts, stops or restarts dq_transcribe or the device agent.
  Works on Termux, ChromeOS/Linux and macOS.
- **Cross-platform, simple packaging:** Android tablet is the preferred (cheaper)
  target; ChromeOS and Mac are welcome; Windows is low priority. Needs only
  Python 3 (stdlib) and Chrome.
- **No host list.** Officials sign up at the meet; nobody pulls a SWIMS report
  ahead of time. (`host_list` stays reserved in the roster format.)
- **Camera first: "Capture USA Registration".** The tablet camera reads the
  Membership card tab in the official's USA Swimming app. The card has **no
  barcode/QR**, so it is read by **OCR in Chrome (Tesseract.js, bundled under
  `web/vendor/tesseract/`, served from localhost, offline)**. The scanner keeps
  reading frames until every field is read (no shutter tap), cycles page layouts,
  cleans up frames (grayscale, contrast, sharpen) and flips mirrored frames.
  The server parses and merges the OCR text (`card_reader.py`, unit tested).
  Frames are never stored.
- **Validation:** membership good-standing date, background check and athlete
  protection training must be current on the session date → validated
  (`camera`). Otherwise the sign-in goes to the admin, who taps **Looks good**
  (`visual`) or **Remove**. A camera check is reused for later sessions at the same meet.
- **Returning officials:** type a few letters, tap the row: club, zone, years
  certified and last roles are pre-filled. **Zone** comes from the LSC code;
  **years certified** is typed once.
- **Pre-sign-up:** one tap per later session that day on the sign-in sheet.
- **Note:** check-in confirms membership, background check and training. It does
  **not** prove position certifications (stroke & turn, starter, referee). The
  Referee assigns positions.
- **Trainee pairing:** flag every trainee, and later make the team builder refuse
  to leave one unpaired.
- **Sessions:** the meet → days → sessions structure is planned in dq_transcribe
  (plan section 4.0), and session details may come from the Hy-Tek Meet Manager
  file. Keep a simple local session list for now (name, day, start time).

## The handoff contract: the officials roster file

dq_transcribe will add an **"Import officials"** button on its Meet setup page
that reads this file, or fetches it from `http://localhost:8010/roster.json`.
Keep the format stable and versioned; if you need to change it, bump `version`
and write the change down in `ai_docs/officials_roster_format.md` (create it;
you own that file).

```json
{
  "format": "officials-roster",
  "version": 1,
  "generated_at": "2026-10-16T07:45:00-07:00",
  "meet": {"name": "Candy Meet", "start_date": "2026-10-16"},
  "session": {"name": "Friday PM", "date": "2026-10-16", "start_time": "13:00"},
  "officials": [
    {
      "name": "Pat Example",
      "role": "Stroke & Turn Judge",
      "club": "PASA",
      "zone": "Western",
      "years_certified": 6,
      "trainee": false,
      "validated": true,
      "validation_method": "host_list",
      "team": "Team 1",
      "member_id": null
    }
  ]
}
```

- `role` must be one of dq_transcribe's roster roles, exactly as written:
  "Stroke & Turn Judge", "Chief Judge", "Deck Referee", "Meet Referee",
  "Starter", "Relay Take-off Judge", "Admin Official". If the owner adds roles,
  tell him dq_transcribe needs the same change (`MEET_ROSTER_ROLES` in its `constants.py`).
- An official working two roles appears twice, once per role.
- `validation_method`: `host_list`, `camera`, `visual` (admin looked), or `none`.
- `member_id` is optional. Treat it as personal data: never log it, and never put it
  in commit messages or device reports.

## Working in parallel with the dq_transcribe chat

- **Only touch your own files:** `src/officials_signin/`, `tests/officials_signin/`,
  `scripts/start_signin.sh`, `ai_docs/officials_signin_*.md`,
  `ai_docs/officials_roster_format.md`, and device tasks named
  `device_tasks/signin_*.sh`. Do not edit dq_transcribe's code or docs. If
  something there must change, tell the owner and he will relay it.
- Before every push: `git pull --rebase origin main`. Commit small and often, so
  the two chats rarely collide.
- Add your package to `pyproject.toml` only if needed, and tell the owner.
- Tests live in `tests/officials_signin/` and run with
  `PYTHONPATH=src:tests python3 -m unittest discover -s tests/officials_signin`.
  Don't break dq_transcribe's suite (`... discover -s tests`).

## Running things on the tablet (the relay)

You cannot connect to the tablet. Use GitHub as the go-between:
`COMMIT_TRAILERS="<your trailers>" bash scripts/run_on_device.sh device_tasks_source.sh [wait_seconds]`.
It commits your script into `device_tasks/` on `main`. The tablet's
`scripts/device_agent.sh` pulls it, runs it from the repo root (time limit
600 s), and pushes the output to the `device-reports` branch, where the helper
prints it. A round trip takes about 15–40 s.

- The agent runs **whatever is committed** to `device_tasks/`. That is safe only
  because the repo is private and the owner is the only human pusher. Keep tasks
  small, readable and non-destructive: never delete files outside the repo,
  `~/.dq_transcribe` or `~/.officials_signin`; never touch credentials; probe
  read-only first.
- If no report arrives, the agent is stopped. Ask the owner to type
  `dq_transcribe` in Termux (it starts the agent).
- Never restart or kill dq_transcribe's server (`python -m dq_transcribe`) or its
  whisper servers. On Friday 2026-10-16 the owner is recording a real meet with it.

## Environment facts

- Tablet: Lenovo Idea Tab, Android 16, 8 GB RAM. Termux from Google Play, with
  all-files access. **No Termux:API.** Chrome is the UI. `localhost` counts as a
  secure context (camera and microphone allowed).
- Python stdlib only on the server (`http.server.ThreadingHTTPServer`, `sqlite3`
  with WAL), like dq_transcribe. Web files are served as `string.Template`, so
  they must never contain a literal dollar sign (or switch to a different
  templating approach for your app and say so).
- Your cloud workspace reaches GitHub and the package registries (pip, npm), not
  arbitrary websites.

## Status and next steps

Done (2026-10-15): app scaffold, camera card reading, fast sign-in with returning
officials, admin exceptions (Looks good / Remove), per-session and later-session
sign-up, `/roster.json` + download, tests (`tests/officials_signin`).

Also done (2026-10-15): session type and officials meeting time, delete session,
team builder (rules in `ai_docs/officials_signin_memory.md`), camera diagnostics,
self-restart of the sign-in server on code changes.

Also done (2026-10-16): Edit button with duplicate merge, full-resolution photo for
card reads, live guide with sideways hint, printouts (session, meet, team page),
estimated session length with a rotation schedule, fixed / rotating ends, demo meet
(`/demo`).

Next:
1. Owner feedback on the printouts, the rotation modes and the demo (see the open
   items in `ai_docs/officials_signin_memory.md`).
2. Faster mirrored card reads. Ask before starting anything on the tablet.
3. Keep `ai_docs/officials_signin_memory.md` and this file current before each pause.
