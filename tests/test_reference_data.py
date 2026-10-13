"""Sanity checks for the DQ code reference tables in reference/dq_codes/."""

from __future__ import annotations

import csv
import unittest
from pathlib import Path

REFERENCE_DIRECTORY = Path(__file__).resolve().parent.parent / "reference" / "dq_codes"
CURRENT_TABLE = REFERENCE_DIRECTORY / "dq_codes_rev-2024-01.csv"
OLD_TABLE = REFERENCE_DIRECTORY / "dq_codes_rev-2019-07.csv"
EXPECTED_COLUMNS = ["code", "section", "group", "description", "detail_field", "slip_has_phase_boxes"]
ALLOWED_DETAIL_FIELDS = {"", "turn_number", "stroke_number", "swimmer_number", "swimmer_and_stroke", "free_text"}
# Printed twice on the rev. 7/19 slip ("Delay initiating turn" and "Other").
KNOWN_DUPLICATES_2019 = {"2T"}


def read_table(path: Path) -> list[dict[str, str]]:
    """Read a code table as a list of row dictionaries."""
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == EXPECTED_COLUMNS, reader.fieldnames
        return list(reader)


def duplicate_codes(rows: list[dict[str, str]]) -> set[str]:
    """Codes that appear on more than one row (blank codes ignored)."""
    seen: set[str] = set()
    duplicates: set[str] = set()
    for row in rows:
        code = row["code"]
        if code and code in seen:
            duplicates.add(code)
        seen.add(code)
    return duplicates


class ReferenceTableTests(unittest.TestCase):
    """The code tables are well-formed and match what the slips print."""

    def test_current_codes_are_unique(self) -> None:
        self.assertEqual(duplicate_codes(read_table(CURRENT_TABLE)), set())

    def test_old_table_has_only_the_known_duplicate(self) -> None:
        self.assertEqual(duplicate_codes(read_table(OLD_TABLE)), KNOWN_DUPLICATES_2019)

    def test_fields_use_allowed_values(self) -> None:
        for path in (CURRENT_TABLE, OLD_TABLE):
            for row in read_table(path):
                self.assertIn(row["detail_field"], ALLOWED_DETAIL_FIELDS, row)
                self.assertIn(row["slip_has_phase_boxes"], {"yes", "no"}, row)
                self.assertTrue(row["description"], row)

    def test_spot_check_known_codes(self) -> None:
        current = {row["code"]: row for row in read_table(CURRENT_TABLE)}
        self.assertEqual(current["2A"]["description"], "No touch at turn")
        self.assertEqual(current["2A"]["detail_field"], "turn_number")
        self.assertEqual(current["1K"]["description"], "Not separated")
        self.assertEqual(current["7A"]["description"], "False start")


if __name__ == "__main__":
    unittest.main()
