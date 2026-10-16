# Officials Sign-In: memory (decisions, facts, open items)

Kept current by the assistant working on `src/officials_signin/`. Newest first
within each section.

## Decisions

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
- **Team builder rules:** ask the owner (trainees must be paired with a certified
  official; the builder must refuse to leave one unpaired).
- Certifications tab: could it give years certified or position certifications?
  Ask for a screenshot.
- `pyproject.toml` does not list the package data for `officials_signin` (not needed
  when running from source with `PYTHONPATH=src`). Add it if the app is ever pip-installed.
- dq_transcribe side: "Import officials" button reading `/roster.json` (owner relays
  to the dq_transcribe chat).
