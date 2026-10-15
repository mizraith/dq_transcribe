"""Shared test helpers: synthetic WAV audio and a fake speech engine."""

from __future__ import annotations

import array
import io
import math
import wave
from pathlib import Path

from dq_transcribe import constants
from dq_transcribe.transcriber import TranscriptionResult

TONE_FREQUENCY_HZ = 440.0
TONE_AMPLITUDE = 0.3
FAKE_MODEL_NAME = "fake-model"
FAKE_RAW_OUTPUT = "{}"


def build_wav_bytes(pattern: list[tuple[str, float]], sample_rate: int = constants.AUDIO_SAMPLE_RATE_HZ) -> bytes:
    """Build a mono 16-bit WAV from a pattern of tone and silence sections.

    Args:
        pattern: Sections as ``("tone" | "silence", seconds)`` pairs.
        sample_rate: Samples per second.

    Returns:
        The complete WAV file contents.
    """
    samples = array.array("h")
    for kind, seconds in pattern:
        for index in range(int(seconds * sample_rate)):
            if kind == "tone":
                value = TONE_AMPLITUDE * math.sin(2 * math.pi * TONE_FREQUENCY_HZ * index / sample_rate)
                samples.append(int(value * constants.FULL_SCALE_AMPLITUDE))
            else:
                samples.append(0)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(constants.AUDIO_CHANNEL_COUNT)
        wav_file.setsampwidth(constants.WAV_SAMPLE_WIDTH_BYTES)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(samples.tobytes())
    return buffer.getvalue()


def write_wav(path: Path, pattern: list[tuple[str, float]]) -> Path:
    """Write a synthetic WAV to ``path`` (creating folders) and return the path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(build_wav_bytes(pattern))
    return path


class FakeTranscriber:
    """Stand-in speech engine that returns numbered text for each call."""

    model_name = FAKE_MODEL_NAME

    def __init__(self, fail: bool = False, prefix: str = "turn", model_name: str = FAKE_MODEL_NAME) -> None:
        self.fail = fail
        self.prefix = prefix
        self.model_name = model_name
        self.call_count = 0

    def transcribe(self, wav_path: Path) -> TranscriptionResult:
        """Return ``"<prefix> N"`` (or raise if constructed with ``fail=True``)."""
        self.call_count += 1
        if self.fail:
            raise RuntimeError("fake failure")
        return TranscriptionResult(f"{self.prefix} {self.call_count}", FAKE_RAW_OUTPUT)
