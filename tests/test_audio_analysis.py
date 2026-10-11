"""Tests for dq_transcribe.audio_analysis."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dq_transcribe.audio_analysis import UnsupportedAudioError, analyze_clip, read_mono_wav
from helpers import write_wav

TONE = "tone"
SILENCE = "silence"


class AnalyzeClipTests(unittest.TestCase):
    """Turn detection on synthetic audio."""

    def setUp(self) -> None:
        self.directory = Path(tempfile.mkdtemp())

    def _analyze(self, pattern):
        return analyze_clip(read_mono_wav(write_wav(self.directory / "a.wav", pattern)))

    def test_long_pause_splits_into_two_turns(self) -> None:
        analysis = self._analyze([(TONE, 2.0), (SILENCE, 1.5), (TONE, 2.0)])
        self.assertEqual(len(analysis.turns), 2)

    def test_short_pause_stays_one_turn(self) -> None:
        analysis = self._analyze([(TONE, 2.0), (SILENCE, 0.3), (TONE, 2.0)])
        self.assertEqual(len(analysis.turns), 1)

    def test_turns_cover_the_tone(self) -> None:
        analysis = self._analyze([(TONE, 2.0), (SILENCE, 1.5), (TONE, 2.0)])
        first, second = analysis.turns
        self.assertLess(first.start_seconds, 0.2)
        self.assertGreater(first.end_seconds, 1.9)
        self.assertLess(second.start_seconds, 3.6)
        self.assertGreater(second.end_seconds, 5.4)

    def test_stereo_is_rejected(self) -> None:
        import wave

        path = self.directory / "stereo.wav"
        with wave.open(str(path), "wb") as wav_file:
            wav_file.setnchannels(2)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16000)
            wav_file.writeframes(b"\x00\x00" * 200)
        with self.assertRaises(UnsupportedAudioError):
            read_mono_wav(path)


if __name__ == "__main__":
    unittest.main()
