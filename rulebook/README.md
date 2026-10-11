# Rulebooks

Local, dated copies of the rule documents the app depends on. DQ codes and rules
change almost every year, so every file is kept under its own dated name and old
copies are never overwritten. When a new edition comes out, add it next to the old
one and record it in the table below.

**File naming:** `<source>-<document>-<edition year>_downloaded-<YYYY-MM-DD>.pdf`

| File | Document | Edition | PDF created | Downloaded | Source | SHA-256 |
|------|----------|---------|-------------|------------|--------|---------|
| `usa-swimming-rulebook-2026_downloaded-2026-10-10.pdf` | 2026 USA Swimming Rules and Regulations (140 pages, 13 MB) | 2026 | 2026-01-05 | 2026-10-10 | <https://www.usaswimming.org/rulebook>, which redirects to `websiteprodcoresa.blob.core.windows.net/.../rulebooks/2026-rulebook.pdf` | `4c95410b2f3f7ac39913a1d9bf752be9a623f6152e3ecc2baba9695f6e8ca5c1` |

## Most relevant sections for dq_transcribe (2026 edition)

- **Part One, Technical Rules**
  - **Article 101 (p. 23):** Individual strokes and relays (starts, breaststroke, butterfly,
    backstroke, freestyle, IM, relays). This is the source of most DQ descriptions.
  - **Article 102 (p. 28):** Conduct and officiating, including officials, referee, judges,
    disqualifications and protests.
- **Front matter:** "Major Legislation and Rule Changes for 2026", to check what changed
  each year.

## How to refresh

The cloud workspace cannot reach usaswimming.org, so the download runs on the
tablet. See `device_tasks/download_rulebook.sh` (it pushes the file to a temporary
`rulebook-import` branch, which is then merged into `main` with this table updated).
