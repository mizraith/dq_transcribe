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
# Layout where OCR prints the label column, then the date column (seen with page layout 3).
COLUMN_LAYOUT_TEXT = f"""Official @
PAT "SKIP" EXAMPLE
Member Id: {FAKE_MEMBER_ID}
LSC & Club: PC - PASA
In Good Standing Until:
Expiration Date:
Background Check:
Athlete Protection Training:
Concussion Protocol Training:
(CANRA) Mandatory Reporting:
Understanding Your Responsibility:
09/21/2027
12/31/9999
09/30/2027
09/21/2027
01/01/3000
01/01/3000
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
        result = check_card(read_card([text, text]), SESSION_DATE)  # confirmed by two passes
        self.assertFalse(result.validated)
        self.assertEqual(result.problems, ["Background check: expired 2026-09-30"])

    def test_date_on_the_session_day_is_still_current(self) -> None:
        text = CLEAN_CARD_TEXT.replace("Until: 09/21/2027", "Until: 10/16/2026")
        self.assertTrue(check_card(parse_card_text(text), SESSION_DATE).validated)

    def test_unread_fields_are_reported(self) -> None:
        result = check_card(parse_card_text(TOP_HALF_TEXT), SESSION_DATE)
        self.assertFalse(result.validated)
        self.assertIn("Background check: not read", result.problems)


class GoodStandingTests(unittest.TestCase):
    """The good-standing row is the hardest to read; several fallbacks cover it."""

    def test_ocr_slip_in_the_label_is_tolerated(self) -> None:
        text = CLEAN_CARD_TEXT.replace("In Good Standing Until", "In Good Standinq Untii")
        self.assertEqual(parse_card_text(text).good_standing_until, "2027-09-21")

    def test_label_and_date_columns_are_paired_in_order(self) -> None:
        reading = parse_card_text(COLUMN_LAYOUT_TEXT)
        self.assertEqual(reading.good_standing_until, "2027-09-21")
        self.assertEqual(reading.expiration_date, "9999-12-31")
        self.assertEqual(reading.background_check_until, "2027-09-30")
        self.assertEqual(reading.athlete_protection_until, "2027-09-21")

    def test_columns_are_not_paired_when_counts_differ(self) -> None:
        text = COLUMN_LAYOUT_TEXT.replace("12/31/9999\n", "")
        self.assertIsNone(parse_card_text(text).good_standing_until)

    def test_banner_covers_an_unread_good_standing_date(self) -> None:
        text = CLEAN_CARD_TEXT.replace("In Good Standing Until: 09/21/2027", "In Good Standing Until:")
        reading = parse_card_text(text)
        self.assertIsNone(reading.good_standing_until)
        self.assertTrue(reading.good_standing_banner)
        self.assertTrue(reading.is_complete)
        self.assertTrue(check_card(reading, SESSION_DATE).validated)

    def test_without_banner_or_date_good_standing_is_missing(self) -> None:
        text = CLEAN_CARD_TEXT.replace("In Good Standing Until: 09/21/2027", "").replace("In good standing\n", "")
        reading = parse_card_text(text)
        self.assertIn(constants.CARD_FIELD_GOOD_STANDING_UNTIL, reading.missing_fields)
        self.assertFalse(check_card(reading, SESSION_DATE).validated)


class OcrSlipTests(unittest.TestCase):
    """A single misread must not send a valid official to the admin, or garble the name."""

    def test_misread_labels_still_anchor_the_name(self) -> None:
        text = CLEAN_CARD_TEXT.replace("Official @", "ficial (v]").replace("Member Id", "Member ld")
        reading = parse_card_text(text)
        self.assertEqual(reading.name, 'Pat "Skip" Example')
        self.assertEqual(reading.member_id, FAKE_MEMBER_ID)
        self.assertTrue(reading.is_official)
        self.assertEqual(parse_card_text(text.replace("Member ld", "Member Ia")).member_id, FAKE_MEMBER_ID)

    def test_expiry_read_once_is_unconfirmed(self) -> None:
        misread = CLEAN_CARD_TEXT.replace("Until: 09/21/2027", "Until: 09/21/2021").replace("In good standing\n", "")
        result = check_card(read_card([misread]), SESSION_DATE)
        self.assertFalse(result.validated)
        self.assertEqual(result.unconfirmed, [constants.CARD_FIELD_GOOD_STANDING_UNTIL])

    def test_expiry_read_twice_is_confirmed(self) -> None:
        expired = CLEAN_CARD_TEXT.replace("Until: 09/21/2027", "Until: 09/21/2021")
        result = check_card(read_card([expired, expired]), SESSION_DATE)
        self.assertEqual(result.unconfirmed, [])
        self.assertEqual(result.problems, ["Membership (good standing): expired 2021-09-21"])

    def test_later_correct_reads_outvote_a_slip(self) -> None:
        misread = CLEAN_CARD_TEXT.replace("Until: 09/21/2027", "Until: 09/21/2021")
        reading = read_card([misread, CLEAN_CARD_TEXT, CLEAN_CARD_TEXT])
        self.assertEqual(reading.good_standing_until, "2027-09-21")
        self.assertTrue(check_card(reading, SESSION_DATE).validated)

    def test_stray_letters_around_the_name_are_dropped(self) -> None:
        noisy = CLEAN_CARD_TEXT.replace('PAT "SKIP" EXAMPLE', 'Dil PAT "SKIP" EXAMPLE P')
        self.assertEqual(parse_card_text(noisy).name, 'Pat "Skip" Example')

    def test_name_vote_prefers_the_clean_reading(self) -> None:
        noisy = CLEAN_CARD_TEXT.replace('PAT "SKIP" EXAMPLE', 'PAT "SKIP" EXAMPLE Xq')
        self.assertEqual(read_card([noisy, CLEAN_CARD_TEXT]).name, 'Pat "Skip" Example')


class TidyNameTests(unittest.TestCase):
    """Names from the card."""

    def test_nickname_quotes_kept_and_title_case(self) -> None:
        self.assertEqual(tidy_name('MARY-JO "MJ" O\'NEIL ,'), 'Mary-Jo "Mj" O\'Neil')

    def test_curly_quotes_count_as_straight(self) -> None:
        self.assertEqual(tidy_name("MARK “RED” BYER"), 'Mark "Red" Byer')
        self.assertEqual(tidy_name("PAT O’NEIL"), "Pat O'Neil")

    def test_unmatched_quote_at_an_end_is_dropped(self) -> None:
        self.assertEqual(tidy_name('"MARK "RED" BYER'), 'Mark "Red" Byer')
        self.assertEqual(tidy_name('MARK "RED" BYER"'), 'Mark "Red" Byer')
        self.assertEqual(tidy_name('"RED" BYER'), '"Red" Byer')

    def test_stray_symbols_dropped(self) -> None:
        self.assertEqual(tidy_name("PAT | EXAMPLE @"), "Pat Example")


if __name__ == "__main__":
    unittest.main()
