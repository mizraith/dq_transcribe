"""Tests for the text clean-up and prompt loading in dq_transcribe.transcriber."""

from __future__ import annotations

import socket
import stat
import sys
import tempfile
import unittest
from pathlib import Path

from dq_transcribe import constants
from dq_transcribe.transcriber import (
    TranscriberUnavailableError,
    WhisperServerTranscriber,
    clean_transcript_text,
    load_prompt,
)
from helpers import write_wav

FAKE_SERVER_SCRIPT = Path(__file__).resolve().parent / "fake_whisper_server.py"


def free_port() -> int:
    """Ask the OS for a free local port."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


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


class WhisperServerTranscriberTests(unittest.TestCase):
    """The persistent-server transcriber starts, answers, restarts after a crash, and stops."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        # An executable named like the real program, which runs the stand-in server.
        self.server_path = self.root / "whisper-server"
        self.server_path.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE_SERVER_SCRIPT}" "$@"\n')
        self.server_path.chmod(self.server_path.stat().st_mode | stat.S_IXUSR)
        self.model_path = self.root / "ggml-fake.bin"
        self.model_path.write_bytes(b"model")
        self.wav_path = write_wav(self.root / "turn.wav", [("tone", 0.5)])
        self.transcriber = WhisperServerTranscriber(
            free_port(),
            server_path=self.server_path,
            model_path=self.model_path,
            library_directory=self.root,
            log_directory=self.root,
            startup_timeout_seconds=15,
        )

    def tearDown(self) -> None:
        self.transcriber.stop()

    def test_transcribes_and_cleans_text(self) -> None:
        result = self.transcriber.transcribe(self.wav_path)
        self.assertEqual(result.text, "reply 1 file=True")
        self.assertIn("[Music]", result.raw_output)
        self.assertEqual(self.transcriber.model_name, "ggml-fake")

    def test_restarts_after_the_server_dies(self) -> None:
        self.transcriber.transcribe(self.wav_path)
        self.transcriber._process.kill()  # simulate a crash
        self.transcriber._process.wait()
        result = self.transcriber.transcribe(self.wav_path)
        self.assertEqual(result.text, "reply 1 file=True")  # a fresh server counts from 1 again

    def test_missing_program_is_reported(self) -> None:
        self.server_path.unlink()
        with self.assertRaises(TranscriberUnavailableError):
            self.transcriber.transcribe(self.wav_path)


if __name__ == "__main__":
    unittest.main()
