# Officials Sign-In: memory (decisions, facts, open items)

Kept current by the assistant working on `src/officials_signin/`. Newest first
within each section.

## Decisions

- **2026-10-16 (night): Meets view, new Meet setup, demo reset, mirror memory, coaches hook.**
  - **Meets** (header button, Meet overview): every meet with Open, "+ New meet", and the
    demo meet (Open, Reset demo behind a 10-second warning, as in dq_transcribe). Opening a
    real meet leaves demo mode; it picks today's session, else the next one, else the last.
    The purple demo banner also has Reset demo.
  - **Meet setup** rebuilt (owner: "Start a different meet" was confusing): the meet's
    name and start date, then its sessions as **table rows** (type, date, start, officials
    meeting, name, hours, signed in, Delete). "+ Add session" adds a row that follows the
    last one (after a morning session: same day; otherwise the next day at the same time
    and type). Save sends the meet and every row in one request (`/api/meets/save`, one
    transaction: a bad row saves nothing). Deleting a saved session asks first (warning
    under the table). Every pop-up has an ✕ in the top right; Meet setup's Save/Cancel stay
    pinned at the bottom.
  - **Rotation #1 confirmed** by the owner: fixed ends means 1 and 2 at S, 3 and 4 at T
    (which pair is arbitrary). Implemented as (1, 3), (2, 4).
  - **Mirrored card reads** (28.7 s -> 14 s first time, ~5.5 s after): the half turn and the
    mirror are tried in parallel on the first still, the way that worked is applied to the
    second still, and a mirror is remembered per camera and picture source in
    localStorage (`officials_signin.mirrored.<camera>.<photo|video>`).
  - **Coaches page** plugs in at `/coaches` through `officials_signin/coaches.py`
    (`server._coaches_module`; handoff in `ai_docs/coaches_signin_handoff.md`, built by
    another chat). `CardScanner.scan` takes `readingRoute` so it can post to its own API.
  - **Privacy (owner, standing rule): never push his card to a repo.** The card example
    in `card_reader.py` held his real member ID (since the first commit) and his name was
    used in examples; both replaced with made-up ones. `test_signin_no_personal_data.py`
    fails on any tracked picture or unredacted member ID. The old commits still contain
    the ID: removing it from history needs a force push (asked the owner).
- **2026-10-16: printouts, rotation schedule, demo meet, guide hints.**
  - Printouts (`reports.py`, `web/print.css`, plain HTML so the browser's Print works):
    `/print/session` (one session, one page: name, roles, team/job, club, zone, years,
    check), `/print/meet` (every session, compact, sessions flow one after another, no page
    per session), `/teams/display` (team cards plus rotation table; big type on screen for
    phone photos, one printed page). In print every row stays on one line; sessions over
    `PRINT_DENSE_ROW_COUNT` (40) rows use smaller type. Checked with the demo: a session of
    up to about 50 officials prints on 1 page; 75 spills to 2. No member IDs on any printout.
  - New session field "Estimated length" (`estimated_minutes`, default 240). The team
    page lists a row per 30-minute slot over that length: time, team at S (start end),
    team at T (turn end).
  - Rotation modes (owner, 2026-10-16), choice "Ends: Fixed / Rotating" on the Teams screen
    (`rotation_mode`, per session, default fixed):
    - 4 teams fixed: (1, 3), (2, 4), repeat. 4 teams rotating: (1, 3), (2, 4), (3, 1),
      (4, 2) ("1 bumps 4 and 3 bumps 2").
    - 3 teams rotating: (1, 2), (3, 1), (2, 3) (the rested team takes S, the S team walks
      down and bumps T, the T team rests). 3 teams fixed: (1, 2), (3, 2), (1, 3) (Team 3
      relieves Team 1, then Team 2, then rests).
    - 4 teams fixed: 1 and 2 at S, 3 and 4 at T (confirmed by the owner).
  - Demo meet (`demo.py`, `/demo`): a separate SQLite file (`~/.officials_signin/demo.db`),
    picked per browser by the cookie `officials_signin_demo=1`; the real meet and the
    roster that dq_transcribe fetches (no cookie) are never touched. The user picks judges,
    trainees, sessions and head officials; names and clubs (`DMOA`...) are made up.
    Everyone works the first session, about 85% each later one, one judge is left "needs
    admin". A purple banner shows demo mode, with New demo and Back to the real meet.
  - Live guide, from the owner's tablet scans: sharpness threshold 30 (sharp 42-116,
    blurry 2-27 there), screen must cover 15% of the frame, and an upright phone that runs
    off the top or bottom gets "Turn the phone sideways so the whole screen fits".
- **2026-10-15 (late): Edit, full-resolution photo, name check.** Owner: names are used
  to credit officials after the meet, so they must be right, and a mistaken "Sign in" must
  be fixable. Every signed-in row has **Edit** (name, years, roles, trainee); renaming
  fixes the official everywhere and merges a duplicate record with the same name (the
  tablet had "Pat \"Skip\" Sample" typed and "Pat Skip Sample" from the card). A name read by
  the camera for someone new is highlighted "check the spelling". Root cause of the
  tablet misreads: video frames are 1920x1080, so a phone at arm's length leaves the name
  ~9 px tall. The still is now a real photo (ImageCapture.takePhoto, full sensor
  resolution, focuses first) with video frames as backup; each still has its own screen
  box and orientation (a photo can come out turned), with a half-turn retry. Diagnostics
  now save the stills (the old code passed a canvas where a video was expected, so no
  still images were saved). Headless Chrome, 4x throttle: 5.2 s upright and sideways.

- **2026-10-15: still capture with a live guide (owner: names must be right; reads must
  take about 5 s).** The camera window no longer OCRs live frames. About 8 times a second a
  480-px preview frame is checked (no OCR): phone screen found (cell grid: bright
  "background" cells, grouped, most text-like group wins; the old row/column finder
  missed upright phones that span ~30% of the width), not touching the frame edge, long
  side >= 45% of the frame's short side, still (motion <= 6), sharp (contrast-normalised
  Laplacian >= 10; test photos: sharp 17-50, slight blur 12-14, blur ~5). A coloured frame
  and hint guide the official (red/amber/green). After ~0.5 s of green a burst of 4 frames
  is taken, the sharpest 2 kept, cropped to the screen, turned upright (text-direction
  test: upright <= 0.09, sideways >= 6.8; the dark header bar shows which way up), turned
  black-and-white with an adaptive threshold (Tesseract's own threshold dropped the grey
  values next to dark phone edges), and read by both workers in parallel. Incomplete:
  back to the guide. "Capture now" forces a capture. The OCR engine warms up with a tiny
  recognize at page load (first passes took 18-35 s on the tablet). Tablet diagnostics:
  front camera has manual focus only; rear has continuous AF. Headless Chrome at 4x CPU
  throttle, from the tap: upright 4.0 s, sideways 4.2-6.3 s, mirrored 7.2 s.
- **2026-10-15: names.** A new official's name must be read the same in two passes; a card
  matched by member ID keeps the stored name; the sign-in sheet's name (editable) wins
  over OCR; curly quotes and an unmatched quote at either end are tidied.

- **2026-10-15: camera choice, sideways phones, screen crop.** The tablet's Chrome gave
  the rear camera even when asked for the front, so "Switch camera" now steps through
  the real cameras by device ID, shows which one is in use ("Front camera (1 of 2)")
  and remembers it. The owner wants to hold phones sideways (fits the wide frame), so
  the scanner tries upright, turned left/right and mirrored until card words appear,
  locks that orientation, and unlocks after 2 misses. Each frame is cropped to the
  phone screen (largest bright block): dark borders/background made Tesseract drop
  the value column. Labels tolerate "Member ld/Ia" and "ficial". Headless Chrome at
  4x throttle: 3.8–4.9 s for upright, sideways both ways, mirrored and screenshot.

- **2026-10-15: team builder (owner's rules).** Only certified Stroke & Turn judges go
  into teams named "Team 1".."Team N"; two teams on deck (one per end), rotating every
  30 min. Team count: of 4 and 3 teams, the one leaving the fewest over wins; on a tie
  4 (8→4×2, 9→3×3, 12→4×3, 13→4×3+ACJ, 14→4×3+2, 15→3×5 with 4×3+3 offered, 6→3×2,
  2→2×1). No jurisdiction limit. Equal team sizes always. Seniority blocks: Team 1 =
  most years certified. Leftovers: suggested most senior first as ACJ, then 15 m, then
  Relief (the admin chooses who really does them). Option "Include 15 m on every team"
  (default off): least senior non-lead member of each team on the 15 m mark; toggling
  it keeps hand changes. Team Lead: none by default, one per team. Trainees shadow a
  mentor (round robin over teams, most senior free member), not counted; the Teams
  screen will not close while a trainee is unpaired. Lanes are per session (default 8).
  Jurisdictions split as evenly as possible, mirrored (3-3-2 / 2-3-3). ACJ, Relief and
  15 m are roster `assignment` values, not roles, so dq_transcribe's roles are unchanged.
- **2026-10-15: the sign-in server restarts itself** when its Python code changes and
  compiles (the tablet's server had kept old code after a pull and broke Meet setup).
- **2026-10-15: camera diagnostics** ("Save frames for troubleshooting" in the camera
  window) save camera settings, raw frames, OCR text and timings to
  `~/.officials_signin/diagnostics/<scan>/`. The owner is testing on the tablet; the
  frames show his card, so delete them once reviewed.
- **2026-10-15: sessions can be deleted** (Edit session → Delete, big warning).

- **2026-10-15: camera speed.** The owner held the phone up ~10 s on the tablet. Now two
  Tesseract workers read the newest frame in parallel ("snapshots processed as we go"),
  layout 6 goes first (reads every field of the sample photo in one pass), empty frames
  cost one pass (no mirrored retry; mirroring is detected from text with no card words),
  and a worker race that flipped orientation back was fixed. Headless Chrome at 4x CPU
  throttle: 2–6 s for the three samples. Not yet re-measured on the tablet.
- **2026-10-15: good standing.** Owner reported the good-standing row was never read on the
  tablet. Labels now tolerate OCR slips, label/date columns printed separately are paired,
  and the green "In good standing" banner counts when the date is not read.
- **2026-10-15: OCR slips on dates.** A pass read 2027 as 2021. A date that looks expired
  must be read the same in two passes before the scanner stops; if time runs out the
  admin sees "read as expired … only once, please check the card".
- **2026-10-15: sessions** have a type (drop-down: Timed Finals, Prelims, Finals, AM, PM,
  A, B, C, Other…) and an optional officials meeting time, defaulting to one hour
  before the start and editable; shown in the header as "Officials Meeting: 12:00 PM".
  Sessions can be edited from Meet setup. Names are suggested ("Friday Prelims",
  "Friday Session A").

- **2026-10-15: OCR runs in Chrome (Tesseract.js), not in Termux.** The owner wants
  simple packaging and cross-platform installs (Android tablet first because it is
  cheaper; ChromeOS and Mac are welcome; Windows is low priority). The engine
  (`tesseract.js@7.0.0`, SIMD+LSTM core, English `tessdata_best` integer model,
  about 6.8 MB) is bundled in `src/officials_signin/web/vendor/tesseract/` and
  served from localhost, so it works offline. The Python server stays stdlib-only.
- **2026-10-15: camera first, no host list.** Officials sign up at the meet; the
  host does not pull a SWIMS report ahead of time. The primary path is the
  **"Capture USA Registration"** button: the tablet camera reads the Membership
  card in the official's USA Swimming app. A host-list importer is not planned
  (`host_list` stays reserved in the roster format).
- **2026-10-15: same repo, port 8010, data in `~/.officials_signin/`** (owner confirmed).
- **2026-10-15: photos are not kept.** Frames are processed in the browser and
  discarded; only parsed fields are stored. The member ID is stored (to match
  returning officials) but never logged and never sent to the page's official list.
- **Zone** is derived from the card's LSC code (table of all 59 LSCs in
  `constants.LSC_CODES_BY_ZONE`). **Years certified** is typed once and stored as
  a starting year.
- **Validation rule:** "In Good Standing Until", "Background Check" and "Athlete
  Protection Training" dates must not be before the session date, and the member
  ID must be read. A camera check is reused for later sessions **at the same meet**
  only.
- Templates are `string.Template` files, so `signin.html`, `signin.js` and
  `card_scanner.js` contain no literal dollar sign (and so no JS template literals).
  Vendor files are served as-is, never templated.

## Facts

- The USA Swimming app's **Membership card** tab shows: green "In good standing"
  banner, "Official ✓", NAME (caps, nickname in quotes), "Member Id:" (14
  letters/digits), "LSC & Club: PC - PASA", "In Good Standing Until", "Expiration
  Date" (often 12/31/9999), "Background Check", "Athlete Protection Training",
  "Concussion Protocol Training", "(CANRA) Mandatory Reporting". **No barcode or QR
  code.** A "Certifications" tab exists (not used yet).
- OCR experiments (owner's screenshot and a mirrored front-camera photo, not
  committed because they contain personal data): page layouts 4 and 6 read
  different rows, so the scanner cycles layouts and merges passes by vote;
  grayscale + auto-contrast + light sharpening recovers the grey values; mirrored
  frames are detected (no labels found) and flipped. In headless Chrome with the
  photo as a fake camera, all fields were read in 2–3 s (cloud CPU; the tablet
  will be slower).

## Open items

- The tablet's diagnostics folder holds frames with the owner's card: keep it as test
  data (owner, 2026-10-16), never copy it into the repo.
- Member ID in old commits (see the 2026-10-16 night decision): history rewrite pending
  the owner's answer.

- **Test on the tablet:** camera permission, front vs back camera, scan speed and
  accuracy in pool lighting. Ask the owner before starting the server there.
- Certifications tab: could it give years certified or position certifications?
  Ask for a screenshot.
- `pyproject.toml` does not list the package data for `officials_signin` (not needed
  when running from source with `PYTHONPATH=src`). Add it if the app is ever pip-installed.
- dq_transcribe side: "Import officials" button reading `/roster.json` (owner relays
  to the dq_transcribe chat).
