"""Tests for officials_signin.card_reader (OCR text of a membership card -> fields).

The sample texts imitate real Tesseract output for the USA Swimming app's
membership card, including typical OCR noise, with a made-up name and member ID.

Run from the repo root with:
    PYTHONPATH=src:tests python3 -m unittest discover -s tests/officials_signin
"""

from __future__ import annotations

import unittest
from datetime import date

from officials_signin import constants
from officials_signin.card_reader import check_card, merge_readings, parse_card_text, read_card, tidy_name

FAKE_MEMBER_ID = "1234ABCD5678EF"
CLEAN_CARD_TEXT = f"""4:48

< Back to My Profile

Membership card Certifications
In good standing
Official @ dusal
|y
PAT "SKIP" EXAMPLE

Member Id: {FAKE_MEMBER_ID}
LSC & Club: PC - PASA

In Good Standing Until: 09/21/2027
Expiration Date: 12/31/9999
Background Check: 09/30/2027
Athlete Protection Training: 09/21/2027
Concussion Protocol Training: 01/01/3000
(CANRA) Mandatory Reporting: 01/01/3000
"""
# A camera pass that read the top half (with a garbage line above the ID) but no dates.
TOP_HALF_TEXT = f"""Official @
PAT "SKIP" EXAMPLE
COT7OQNANEAF
Member Id: {FAKE_MEMBER_ID}
LSC & Club: PC -PASA
In Good Standing Until:
Background Check:
Athlete Protection Training:
"""
# Another pass that read the dates but not the club.
DATES_TEXT = """Official @ <p
PAT "SKIP" EXAMPLE ,
: 5c & : PC-PASA :
Co In Good Standing Until: 09/21/2027 .
: 2 | Background Check: 09/30/2027
Athlete Protection Training: 09/21/2027 A
"""
MIRRORED_TEXT = """slito1d YM ot Nosd —>
2noitsoitined bis> qide1sdmoM
fIYd "OIA" AAAM
"""
SESSION_DATE = date(2026, 10, 16)


class ParseCardTextTests(unittest.TestCase):
    """One OCR pass."""

    def test_clean_card_reads_every_field(self) -> None:
        reading = parse_card_text(CLEAN_CARD_TEXT)
        self.assertEqual(reading.name, 'Pat "Skip" Example')
        self.assertEqual(reading.member_id, FAKE_MEMBER_ID)
        self.assertEqual((reading.lsc, reading.club), ("PC", "PASA"))
        self.assertEqual(reading.good_standing_until, "2027-09-21")
        self.assertEqual(reading.expiration_date, "9999-12-31")
        self.assertEqual(reading.background_check_until, "2027-09-30")
        self.assertEqual(reading.athlete_protection_until, "2027-09-21")
        self.assertTrue(reading.is_official)
        self.assertTrue(reading.good_standing_banner)
        self.assertTrue(reading.is_complete)
        self.assertEqual(reading.zone, constants.ZONE_WESTERN)

    def test_garbage_line_is_not_taken_as_the_name(self) -> None:
        reading = parse_card_text(TOP_HALF_TEXT)
        self.assertEqual(reading.name, 'Pat "Skip" Example')
        self.assertEqual(reading.member_id, FAKE_MEMBER_ID)
        self.assertIsNone(reading.background_check_until)
        self.assertIn(constants.CARD_FIELD_BACKGROUND_CHECK, reading.missing_fields)

    def test_date_row_is_not_mistaken_for_the_banner(self) -> None:
        self.assertFalse(parse_card_text(TOP_HALF_TEXT).good_standing_banner)

    def test_mirrored_text_finds_no_labels(self) -> None:
        reading = parse_card_text(MIRRORED_TEXT)
        self.assertEqual(reading.labels_found, 0)
        self.assertIsNone(reading.name)

    def test_impossible_date_is_ignored(self) -> None:
        reading = parse_card_text("Background Check: 13/45/2027")
        self.assertIsNone(reading.background_check_until)


class MergeTests(unittest.TestCase):
    """Several passes over the same card."""

    def test_partial_passes_combine_into_a_complete_reading(self) -> None:
        reading = read_card([TOP_HALF_TEXT, DATES_TEXT])
        self.assertTrue(reading.is_complete, reading.missing_fields)
        self.assertEqual(reading.club, "PASA")
        self.assertEqual(reading.athlete_protection_until, "2027-09-21")

    def test_majority_wins_over_a_misread(self) -> None:
        misread = CLEAN_CARD_TEXT.replace(FAKE_MEMBER_ID, "1234ABCD5678FF")
        reading = merge_readings([parse_card_text(text) for text in (misread, CLEAN_CARD_TEXT, CLEAN_CARD_TEXT)])
        self.assertEqual(reading.member_id, FAKE_MEMBER_ID)

    def test_no_passes_gives_an_empty_reading(self) -> None:
        self.assertEqual(read_card([]).labels_found, 0)


class CheckCardTests(unittest.TestCase):
    """Automatic validation from the card dates."""

    def test_current_card_validates(self) -> None:
        result = check_card(parse_card_text(CLEAN_CARD_TEXT), SESSION_DATE)
        self.assertTrue(result.validated)
        self.assertEqual(result.problems, [])

    def test_expired_background_check_needs_the_admin(self) -> None:
        text = CLEAN_CARD_TEXT.replace("Background Check: 09/30/2027", "Background Check: 09/30/2026")
        result = check_card(parse_card_text(text), SESSION_DATE)
        self.assertFalse(result.validated)
        self.assertEqual(result.problems, ["Background check: expired 2026-09-30"])

    def test_date_on_the_session_day_is_still_current(self) -> None:
        text = CLEAN_CARD_TEXT.replace("Until: 09/21/2027", "Until: 10/16/2026")
        self.assertTrue(check_card(parse_card_text(text), SESSION_DATE).validated)

    def test_unread_fields_are_reported(self) -> None:
        result = check_card(parse_card_text(TOP_HALF_TEXT), SESSION_DATE)
        self.assertFalse(result.validated)
        self.assertIn("Background check: not read", result.problems)


class TidyNameTests(unittest.TestCase):
    """Names from the card."""

    def test_nickname_quotes_kept_and_title_case(self) -> None:
        self.assertEqual(tidy_name('MARY-JO "MJ" O\'NEIL ,'), 'Mary-Jo "Mj" O\'Neil')

    def test_stray_symbols_dropped(self) -> None:
        self.assertEqual(tidy_name("PAT | EXAMPLE @"), "Pat Example")


if __name__ == "__main__":
    unittest.main()
