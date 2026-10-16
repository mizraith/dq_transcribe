# Coaches Sign-In: handoff and development prompt

Point a new Claude chat at this file to build the **Coaches Sign-In** page. It is
part of the owner's *Swimming_Admin_Assistant* project (repo `mizraith/dq_transcribe`)
and is built **in parallel** with two other chats: dq_transcribe (the DQ app) and
officials_signin (the officials sign-in desk, whose server this page plugs into).

---

## Your role

You are building a **coaches sign-in page** for the tablet desk at swim meets. Coaches
arriving at the meet show the **Membership card** in the USA Swimming app on their
phone; the tablet camera reads it, the page checks the coach's registration is
current, and the coach is added to the meet's list of coaches.

It **shares the meet and its sessions** with Officials Sign-In: the admin sets up the
meet once (on the officials page, Meet setup) and both pages use it. There are **no
teams** for coaches.

The owner is **Red**: an expert Python developer, new to Android. He works from the
tablet and does **not** copy and paste code or commands. You deliver work by committing
to the repo and run things on the tablet through the GitHub relay (see below).

## What the owner asked for (2026-10-16)

- A Coaches Sign-In page that shares the same meet and session information as the
  Officials Sign-In.
- It does **not** assign teams. It validates the USA Swimming registration and keeps
  a list of the coaches at the meet.
- Each coach has a **Head Coach** flag: off by default, easy to switch on, so the
  admin knows who to approach.
- **A club can have several head coaches** (head age-group coach, head senior coach,
  and sometimes several sites per club, each with its own head coach). Never limit
  head coaches to one per club.

Ask the owner before building (one short message, several questions at once):
1. Should a coach sign in once per **meet**, or per **session** like officials?
2. A **screenshot of a coach's Membership card** (with the member ID covered): a
   coach card may show "Coach" instead of "Official" and other requirements
   (for example Safety Training for Swim Coaches, CPR, Concussion training).
   Which ones must be current for a coach to be "good"?
3. What should the list show and print (name, club, head coach, ...), and is a
   printout or a "head coaches by club" view wanted?
4. Should the demo meet include made-up coaches?

## Read first

- `ai_docs/guidelines.md`: coding standards and safety rules (they apply to you).
- `ai_docs/officials_signin_handoff.md` and `ai_docs/officials_signin_memory.md`:
  how the officials page works, the owner's decisions, the tablet and relay facts.
- `src/officials_signin/server.py` (`_coaches_module`, the plug-in contract below),
  `database.py`, `card_reader.py`, `constants.py`, `web/card_scanner.js`,
  `web/signin.html`, `web/signin.js`: the house style. Copy the patterns.

## How the page plugs in (already built for you)

The officials server (port **8010**, data in `~/.officials_signin/`) already routes
these paths to a module **`src/officials_signin/coaches.py`** as soon as that file
exists:

- `GET /coaches` (the page), `GET /coaches/...` (its own files),
  `GET|POST /api/coaches/...` (its API).
- Your module provides `handle_get(handler, path, query) -> bool` and
  `handle_post(handler, path, payload) -> bool` (`payload` is the decoded JSON
  object). Return False for a path you do not know (the server answers 404). Raise
  `officials_signin.database.SigninError("message for the admin")` for a 400.
- Through `handler` you may use: `handler.database` (the real meet's database, or
  the **demo** database for a browser in demo mode, already chosen for you),
  `handler.in_demo`, `handler._send_json(status, data)`,
  `handler._send_bytes(status, content_type, body)` and
  `handler._send_json_error(status, message)`.
- Once `coaches.py` exists, a **Coaches** button appears in the officials page header
  (`/coaches`). Give your page a button back to the officials page (`/`).

Shared pieces to reuse (do not copy them):

- **Meet and sessions:** `handler.database.get_state()` returns the active meet, its
  sessions and the active session. Do not create or edit meets: Meet setup lives on
  the officials page (link to it).
- **Camera reader:** include `/vendor/tesseract/tesseract.min.js` and
  `/card_scanner.js` in your page, and call `window.CardScanner.scan({...})` the way
  `signin.js` does, passing **`readingRoute`** with your own card-reading API route.
  Your route parses the OCR texts with `officials_signin.card_reader.read_card` and
  checks dates with your own rules (`check_card` checks the official requirements).
  Your route must answer in the same shape as the officials one (see
  `server._handle_card_reading`), including `complete: false` until a new coach's
  name has been read the same way twice.
- **Storage:** your own tables in the same SQLite file, created by your module
  (`CREATE TABLE IF NOT EXISTS coaches ...`, `coach_signins ...`; prefix every table
  with `coach`). Link sign-ins to the officials `meets` / `sessions` IDs.

## Files you own

`src/officials_signin/coaches.py` (split into `coaches_*.py` if it grows),
`src/officials_signin/web/coaches.html`, `src/officials_signin/web/coaches.js`,
`tests/officials_signin/test_coaches_*.py`, `ai_docs/coaches_signin_memory.md`
(your decisions log; keep it current) and this file. Put your constants in
`coaches.py` (or a `coaches_constants.py`), **not** in the officials `constants.py`.

Do not edit any other file. If the officials side must change (a new card field in
`card_reader.py`, a change to the plug-in contract), tell the owner exactly what you
need and he will relay it to the officials chat.

## The owner's standards (non-negotiable)

- Python first, stdlib only on the server. Readable names, no cryptic abbreviations.
- An accurate, well-formatted **docstring for every module, class and function**,
  and a header on every file. Keep them in sync with the code.
- **No magic strings or numbers:** centralize them as constants.
- Web files are `string.Template` files: no literal dollar sign in them (so no
  JavaScript template literals).
- **Automation first, touch first:** big buttons, as few taps as possible for the
  common case; a person is involved only when something is wrong.
- Platform-neutral: Android/Termux first, ChromeOS and Mac nice to have, Windows
  only through WSL (never PowerShell).
- Be honest about what you tested; the camera can only be verified on the tablet.
- End every commit message with the attribution trailers your session gives you.

## Privacy (the owner's rules)

- The **member ID** is personal data: never log it, show it, print it, or put it in
  commit messages or device reports.
- **Never commit a membership card picture, camera frame or diagnostics file** to
  the repo, ever. Diagnostics stay on the tablet in `~/.officials_signin/diagnostics`.
  `tests/officials_signin/test_signin_no_personal_data.py` fails if a picture or an
  unredacted member ID is tracked; keep it passing. Use made-up names in examples
  and tests.

## Process

- Tests: `PYTHONPATH=src:tests python3 -m unittest discover -s tests/officials_signin`
  (and don't break `... discover -s tests`). Test your API through HTTP like
  `tests/officials_signin/test_signin_reports_demo.py` does, including demo mode.
- Before every push: `git pull --rebase origin main`. Commit small and often.
- The officials server restarts itself when its Python files change, so the owner
  only reloads the page after pulling.
- Tablet relay: `COMMIT_TRAILERS="<your trailers>" bash scripts/run_on_device.sh
  device_tasks_source.sh [wait_seconds]`; name your tasks `coaches_*.sh`, keep them
  small, read-only first and non-destructive. Tell the owner before anything long;
  **ask before restarting** anything; never restart or kill dq_transcribe's server
  or its whisper servers.
