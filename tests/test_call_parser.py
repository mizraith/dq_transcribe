"""Tests for number normalization and the rule-based call splitter, using real
transcripts recorded on the tablet (clips 25-52, 2026-10-14)."""

from __future__ import annotations

import unittest

from dq_transcribe.call_parser import FLAG_CODE_CHOICE, FLAG_NOT_UNDERSTOOD, is_acknowledgment, parse_call_group
from dq_transcribe.slip_codes import rank_codes
from dq_transcribe.text_normalization import normalize_spoken_numbers


def utterances(*texts: str) -> list[dict]:
    """Build utterance dictionaries from texts (one clip, consecutive turns)."""
    return [
        {"clip_id": 1, "id": index + 1, "start_seconds": float(index), "end_seconds": index + 0.9, "text": text}
        for index, text in enumerate(texts)
    ]


def summary(calls) -> list[tuple]:
    """(event, heat, lane, infractions, accepted) for each call."""
    return [(c.event, c.heat, c.lane, tuple(c.infractions), c.accepted) for c in calls]


class NormalizeSpokenNumbersTests(unittest.TestCase):
    """Numbers after event/heat/lane/turn become digits; phrases stay words."""

    def test_examples(self) -> None:
        cases = {
            "Event, one, heat, two, lane, three, on the turn, one hand touch.": "Event 1, heat 2, lane 3, on the turn, one hand touch.",
            "Lanes one, three, and four.": "Lanes 1, 3, and 4.",
            "Event three, heat, full, lane two.": "Event 3, heat 4, lane 2.",
            "E46. Butterfly": "Event 46. Butterfly",
            "it was the third turn.": "it was the 3rd turn.",
            "Event twenty one, heat four": "Event 21, heat 4",
        }
        for spoken, expected in cases.items():
            self.assertEqual(normalize_spoken_numbers(spoken), expected)


class ParseCallGroupTests(unittest.TestCase):
    """One clip can hold several calls; each becomes a candidate pointing back at its source."""

    def test_multiple_lanes_and_add_on(self) -> None:  # clip 38
        calls = parse_call_group(utterances(
            "Event 6, heat, four. Lanes one, three, and four. All of them, scissors kick, "
            "and then lane six had a one hand touch at the turn.",
            "Accepted.",
        ))
        self.assertEqual(summary(calls), [
            ("6", "4", "1", ("Kick: scissors",), True),
            ("6", "4", "3", ("Kick: scissors",), True),
            ("6", "4", "4", ("Kick: scissors",), True),
            ("6", "4", "6", ("One hand touch",), True),
        ])
        self.assertTrue(all(call.evidence[0].utterance_id == 1 for call in calls))  # same audio, no copies

    def test_lane_and_lane(self) -> None:  # clip 37
        calls = parse_call_group(utterances("Event six, heat one, lane six and lane seven. One hand touch on turn."))
        self.assertEqual([call.lane for call in calls], ["6", "7"])
        self.assertEqual(calls[0].phases, ["Turn"])

    def test_correction_replaces_numbers(self) -> None:  # clip 32
        calls = parse_call_group(utterances(
            "DQ, heat two, lane three, heat four, sorry, heat two, lane four, event three, delay initiating turn."
        ))
        self.assertEqual(summary(calls), [("3", "2", "4", ("Past vertical at turn: delay initiating turn",), False)])

    def test_follow_up_clip_confirms_instead_of_duplicating(self) -> None:  # clips 42-43
        calls = parse_call_group(utterances(
            "Event 21, heat, four lanes, five and six. Underwater recovery in the butterfly.",
            "Underwater recovery, got it. Accepted. Lane five and six.",
        ))
        self.assertEqual([(c.lane, c.accepted) for c in calls], [("5", True), ("6", True)])

    def test_missing_numbers_are_flagged_not_guessed(self) -> None:  # clip 52
        call = parse_call_group(utterances("Event, heat, lane 2, scissors kick.", "Acknowledged."))[0]
        self.assertEqual((call.event, call.heat, call.lane), (None, None, "2"))
        self.assertIn("event not heard", call.flags)

    def test_unrecognized_call_is_kept(self) -> None:  # clip 48
        calls = parse_call_group(utterances("Full plane 8, shorted pass for grip with the touch on the fish.", "Got it."))
        self.assertEqual(len(calls), 1)
        self.assertIn(FLAG_NOT_UNDERSTOOD, calls[0].flags)
        self.assertTrue(calls[0].accepted)

    def test_short_phrases_need_exact_words(self) -> None:  # clip 28
        calls = parse_call_group(utterances("Event 2, heat 2, lane 4, shoulders past vertical, have to touch."))
        self.assertNotIn("No touch at turn", calls[0].infractions)

    def test_slip_codes_from_stroke_clues(self) -> None:  # clips 29, 42, 51
        fly = parse_call_group(utterances("Event 1, heat 2, lane 5. Breaststroke kick, underwater recovery and a one hand touch."))[0]
        self.assertEqual((fly.stroke, fly.codes), ("Butterfly", ["1B", "1F", "1J"]))  # "breaststroke kick" is a fly infraction
        named = parse_call_group(utterances("Event 21, heat 4, lane 5, scissors kick in the butterfly."))[0]
        self.assertEqual((named.stroke, named.codes), ("Butterfly", ["1C"]))
        stroke_free = parse_call_group(utterances("Event 20, heat 1, lane 1, did not finish."))[0]
        self.assertEqual(stroke_free.codes, ["7C"])

    def test_unknown_stroke_leaves_code_open_with_options(self) -> None:  # clip 26
        call = parse_call_group(utterances("Event 1, heat 2, lane 3, on the turn, one hand touch."))[0]
        self.assertEqual((call.stroke, call.codes, call.code_options), (None, [None], [["1J", "3J"]]))
        self.assertIn("slip code depends on the stroke", call.flags)

    def test_acknowledgments(self) -> None:
        for text in ("Accepted.", "Got it.", "Roger that.", "Good one. Acknowledged. Accepted.", "Confirmed"):
            self.assertTrue(is_acknowledgment(text), text)
        self.assertFalse(is_acknowledgment("Event 4, heat 2, lane 1, one hand touch."))


if __name__ == "__main__":
    unittest.main()


class SlipCodeSuggestionTests(unittest.TestCase):
    """Slip codes for infractions the phrase list names only by group, or not at all."""

    def test_group_phrase_offers_every_code_in_the_group(self) -> None:
        call = parse_call_group(utterances("Possible DQ, event 46, heat 2, lane 4, past vertical at turn."))[0]
        self.assertEqual(call.stroke, "Backstroke")
        self.assertIsNone(call.codes[0])
        self.assertEqual(set(call.code_options[0][:3]), {"2B", "2C", "2D"})
        self.assertIn(FLAG_CODE_CHOICE, call.flags)

    def test_specific_line_replaces_its_group(self) -> None:
        call = parse_call_group(utterances("Event 46, heat 2, lane 4, past vertical at turn, delayed initiating turn."))[0]
        self.assertEqual(call.infractions, ["Past vertical at turn: delay initiating turn"])
        self.assertEqual(call.codes, ["2C"])

    def test_unrecognized_call_still_gets_suggestions(self) -> None:
        call = parse_call_group(utterances("Event 9, heat 1, lane 2, the elbows came out over the water on the recovery."))[0]
        self.assertIn("3H", call.suggested_codes)

    def test_rank_codes(self) -> None:
        self.assertEqual(rank_codes("past vertical at the turn", "Backstroke")[:3], ["2C", "2B", "2D"])
        self.assertEqual(rank_codes("one hand touch"), ["1J", "3J"])
        self.assertEqual(rank_codes("one hand touch", "Breaststroke"), ["3J"])
        self.assertEqual(rank_codes("he delayed initiating the turn"), ["2C", "2B"])
        self.assertEqual(rank_codes("event 5, heat 1, lane 3, thank you"), [])
