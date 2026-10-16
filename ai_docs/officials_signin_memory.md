# Officials Sign-In: memory (decisions, facts, open items)

Kept current by the assistant working on `src/officials_signin/`. Newest first
within each section.

## Decisions

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

- **Test on the tablet:** camera permission, front vs back camera, scan speed and
  accuracy in pool lighting. Ask the owner before starting the server there.
- Certifications tab: could it give years certified or position certifications?
  Ask for a screenshot.
- `pyproject.toml` does not list the package data for `officials_signin` (not needed
  when running from source with `PYTHONPATH=src`). Add it if the app is ever pip-installed.
- dq_transcribe side: "Import officials" button reading `/roster.json` (owner relays
  to the dq_transcribe chat).
