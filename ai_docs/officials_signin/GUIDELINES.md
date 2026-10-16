# Officials Sign-In: guidelines

Standing rules for any AI agent (or person) working on **Officials Sign-In** (with its
Coaches Sign-In page), the second app in the owner's *Swimming_Admin_Assistant*
project. They add to the repo-wide `ai_docs/guidelines.md`, which also applies.

Companion files in this folder: `HANDOFF_PROMPT.md` (start here: what the app is, where
things are, how to work) and `MEMORY.md` (decisions, facts, gotchas and open items,
newest first). Keep all three current before every pause.

## Who you work for

- The owner is **Red**, an expert Python developer, new to Android. He works from the
  tablet (Lenovo Idea Tab, Android 16, Termux + Chrome) and **does not copy and paste code
  or commands**. Deliver by committing to `mizraith/dq_transcribe` (`main`) and run
  things on the tablet through the device relay.
- He sends several requests at once and adds more while you work. Keep a task list,
  answer every point in the final reply, and say plainly what you did not do.
- Ask before building only when a wrong guess is expensive; otherwise make the best
  call, build it, and say which way you went (he will redirect).

## Coding standards (non-negotiable)

- Python first, **standard library only** on the server (`http.server`, `sqlite3`).
- Readable names, no cryptic abbreviations. A docstring on every module, class and
  function and a header on every file (Python, JS, HTML, CSS, shell), kept in sync.
- **No magic strings or numbers**: they live in `src/officials_signin/constants.py`;
  the pages get them through the embedded config (`server.build_web_config`).
- Web pages and scripts are `string.Template` files: **never a literal dollar sign**
  in `web/*.html` / `web/*.js` (no JS template literals). CSS files are served as-is.
- **Share, don't copy** (owner, 2026-10-16): code used by both desk pages lives once:
  `web/desk.css` (styles; the coaches page only overrides colour variables),
  `web/card_camera.js` (camera window), `web/desk_shared.js` (LSC drop-down, club
  label, tab sync), `web/card_scanner.js` (OCR). Never paste a second copy.
- Platform-neutral: Android/Termux first, ChromeOS and Mac nice to have, Windows only
  through WSL (**never PowerShell**).

## Design rules

- **Automation first, touch first**: the deck is busy. Fewest taps for the common case,
  good guesses, a person only for exceptions. Big buttons; nothing needs a keyboard
  except names.
- Every pop-up has an **✕** in the top right; long sheets keep their action buttons
  pinned at the bottom. Destructive actions sit behind a clear red warning.
- Printouts fit one page where they can (session, team page); the meet summary flows
  sessions together to save paper.
- **One meet and session for the whole suite** (owner, 2026-10-16): set up and chosen on
  the Admin Assistant main page (`/`); every app shows the same, and changing the session
  in any app changes it everywhere. Only DQ Transcribe's capture keeps its own target.
- Every app has the standard top bar (☰, bold app name, meet, session drop-down, then its
  workflows) via `Desk.initTopBar`; app links live in the ☰ "Admin Assistant ›" sub-menu.

## Privacy (owner's standing rules)

- The **member ID** is personal data: never log it, show it, print it, export it, or
  put it in commit messages or device reports (device scripts redact it as `[ID]`).
- **Never commit a membership-card picture, camera frame or diagnostics file**, ever.
  Diagnostics stay on the tablet in `~/.officials_signin/diagnostics`.
  `tests/officials_signin/test_signin_no_personal_data.py` must keep passing.
- Use made-up names, clubs and IDs in examples, tests and the demo (`Pat "Skip"
  Sample`, clubs `DMOA`...). The owner's real name and card must not appear.

## Process

- Tests: `PYTHONPATH=src:tests python3 -m unittest discover -s tests/officials_signin`
  (and do not break dq_transcribe's `... discover -s tests`). Add tests with every
  change. Check pages in headless Chromium with Playwright (scripts in the scratchpad;
  a fake camera video tests the card reader) and **look at screenshots**.
- Before every push: `git pull --rebase origin main` (never merge, never force-push).
  End commit messages with the attribution trailers your session gives you.
- Only touch your own files: `src/officials_signin/`, `tests/officials_signin/`,
  `scripts/start_signin.sh`, `scripts/start_admin_assistant.sh`,
  `ai_docs/officials_signin/`, `ai_docs/officials_roster_format.md`, and device tasks
  named `signin_*.sh`. dq_transcribe's code and docs belong to another chat: ask the
  owner to relay changes.
- Be honest about testing: the camera, finger dragging and Chrome-on-Android behaviour
  can only be confirmed on the tablet.

## The tablet (device relay)

- `COMMIT_TRAILERS="<trailers>" bash scripts/run_on_device.sh <script> [wait_seconds]`
  commits the script to `device_tasks/`, the tablet's agent runs it (600 s limit) and
  the report comes back on the `device-reports` branch (~15-40 s round trip).
- **Tell the owner before** anything long-running; **ask before restarting** anything.
  **Never** restart or kill dq_transcribe's server or its whisper servers.
- Tasks are small, readable and non-destructive; read-only probes first. Never delete
  outside the repo, `~/.dq_transcribe` or `~/.officials_signin`; never touch credentials.
- No detached background processes on the tablet (the auto-mode classifier refuses
  them as persistence): keep a task in the foreground within its time limit.
- The sign-in server restarts itself when its Python files change, so after a push the
  tablet only needs the page reloaded. Use the app's own HTTP API
  (`http://127.0.0.1:8010/api/...`) for data changes on the tablet, not raw SQL.
