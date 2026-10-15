"""Tests for the text clean-up and prompt loading in dq_transcribe.transcriber."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dq_transcribe import constants
from dq_transcribe.transcriber import clean_transcript_text, load_prompt


class CleanTranscriptTextTests(unittest.TestCase):
    """Sound labels are removed; spoken words are kept."""

    def test_removes_bracketed_and_starred_labels(self) -> None:
        self.assertEqual(clean_transcript_text(" [Gunshot]  DQ. Event 4 *static* (radio beep) lane 6 "), "DQ. Event 4 lane 6")

    def test_only_labels_becomes_empty(self) -> None:
        self.assertEqual(clean_transcript_text("[Music] [Music]"), "")


class PromptTests(unittest.TestCase):
    """The shipped prompt exists and contains no digits (numbers would leak into transcripts)."""

    def test_shipped_prompt_has_vocabulary_and_no_digits(self) -> None:
        prompt = load_prompt(constants.WHISPER_PROMPT_PATH)
        self.assertIn("DQ", prompt)
        self.assertFalse(any(character.isdigit() for character in prompt))

    def test_missing_prompt_file_gives_empty_prompt(self) -> None:
        self.assertEqual(load_prompt(Path(tempfile.mkdtemp()) / "missing.txt"), "")


if __name__ == "__main__":
    unittest.main()
