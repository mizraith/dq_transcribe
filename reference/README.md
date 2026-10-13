# Reference data

Versioned reference data that DQ detection and the review screens are built on.
DQ slips are revised every year or two and **codes get reused with different
meanings**, so every file carries its revision in its name and old revisions are
kept. **Always store a DQ's code together with the slip revision it came from.**

## DQ slips (`dq_slips/`)

Photos of the USA Swimming "Disqualification Report" slip (desk/referee copy),
provided by the owner on 2026-10-12. The revision is printed at the bottom left as
`rev. (M/YY)` (assumed month/year).

| File | Printed revision | Status |
|------|------------------|--------|
| `usa-swimming-dq-slip_rev-2024-01.jpg` | rev. (1/24) | **Current** |
| `usa-swimming-dq-slip_rev-2019-07.jpg` | rev. (7/19) | Superseded, kept for reference |

## DQ code tables (`dq_codes/`)

Transcribed by hand from the slip photos on 2026-10-12. If a table and its photo
disagree, the photo wins; please report the mistake.

| File | Contents |
|------|----------|
| `dq_codes_rev-2024-01.csv` | Every line of the current slip |
| `dq_codes_rev-2019-07.csv` | Every line of the old slip |
| `code_changes_rev-2019-07_to_rev-2024-01.csv` | Each infraction's code in both revisions, and what changed |

**Columns of the code tables:**

| Column | Meaning |
|--------|---------|
| `code` | Code as printed. Blank if the slip prints none. A range such as `6A-D` means one code per relay swimmer (see notes) |
| `section` | Slip section: Butterfly, Backstroke, Breaststroke, Freestyle, Individual Medley, Article 105, Relays, Miscellaneous |
| `group` | Sub-heading within the section (Kick, Arms, Touch, Cycle, Past vertical at turn), if any |
| `description` | The short description as printed, in sentence case |
| `detail_field` | The extra blank on that line: `turn_number`, `stroke_number`, `swimmer_number`, `swimmer_and_stroke`, `free_text`, or blank |
| `slip_has_phase_boxes` | `yes` if the section has START / SWIM / TURN / FINISH boxes (butterfly, backstroke and breaststroke) |

## Things the slips show that the app must capture

- **When in the race it happened:** the butterfly, backstroke and breaststroke
  sections have **START / SWIM / TURN / FINISH** boxes. A DQ should record that
  phase. The other sections have no boxes.
- **Extra details on some lines:**
  - turn number for "No touch at turn" (backstroke 2A, freestyle 4A);
  - which stroke for an IM stroke infraction (5A);
  - which swimmer for relay infractions;
  - swimmer and stroke for a relay "Changed order" (6L);
  - free text for each "Other" line.
- **People:**
  - **Judge** (printed name, required);
  - **Chief Judge initials** (new in rev. 1/24, optional);
  - **Referee** (printed name);
  - **Notified:** separate blanks for **swimmer** and **coach**.
- **Individual medley:** the official also marks the specific stroke infraction
  further down the slip. The owner notes this is repeated information. The app
  records the 5A stroke number and does not require the duplicate.

## Notes, assumptions and open points

1. **Codes changed meaning between revisions.** For example, `1K` was "No touch"
   in 7/19 but is "Not separated" in 1/24, and `3H` changed meaning too. Use
   `code_changes_rev-2019-07_to_rev-2024-01.csv` before comparing codes across
   years.
2. **Duplicate code on the 7/19 slip:** `2T` is printed for both "Delay initiating
   turn" and "Other". The table keeps both as printed. Rev. 1/24 fixed this
   (`2C` and `2T`).
3. **Relay code ranges (an assumption to confirm):**
   - The 1/24 slip prints `6A-D` for stroke infractions and `6F-H` for early
     take-offs, and the 7/19 slip printed `61-64` and `66-68`.
   - The guess is one code per swimmer: stroke infraction swimmer 1–4 = `6A`–`6D`,
     and early take-off by swimmer 2–4 = `6F`–`6H`. Swimmer 1 cannot leave early.
   - Confirm against Meet Manager's DQ code list.
4. **Removed in 1/24:** breaststroke "Two strokes under" (3G) and "Not in same
   horizontal plane" (3H).
5. **Added in 1/24:** the IM stroke-infraction code `5A`, an "Article 105" line
   (swimmers with a disability, free text) and the Chief Judge initials.
6. **"Head not up"** (3P in 7/19) is now "Head not up before hands turn inward"
   (3R in 1/24).
