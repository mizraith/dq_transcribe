"""Audio analysis for dq_transcribe: loudness, pauses, and turn windows.

Works on mono 16-bit WAV audio using only the standard library. A "turn" is a
stretch of speech between pauses, which for radio traffic corresponds to one
transmission. Every measurement is returned (and stored with the clip) so the
thresholds can be tuned later against real audio and clips reprocessed.
"""

from __future__ import annotations

import array
import math
import sys
import wave
from dataclasses import dataclass
from pathlib import Path

from dq_transcribe import constants


class UnsupportedAudioError(ValueError):
    """Raised when a WAV file is not mono 16-bit PCM."""


@dataclass(frozen=True)
class WavAudio:
    """Decoded mono 16-bit audio.

    Attributes:
        samples: Signed 16-bit sample values.
        sample_rate_hz: Samples per second.
    """

    samples: array.array
    sample_rate_hz: int

    @property
    def duration_seconds(self) -> float:
        """Length of the audio in seconds."""
        return len(self.samples) / self.sample_rate_hz


@dataclass(frozen=True)
class Pause:
    """A quiet stretch of audio, in seconds from the start of the clip."""

    start_seconds: float
    end_seconds: float

    @property
    def duration_seconds(self) -> float:
        """Length of the pause in seconds."""
        return self.end_seconds - self.start_seconds


@dataclass(frozen=True)
class TurnWindow:
    """The time range of one turn of speech, in seconds from the start of the clip."""

    start_seconds: float
    end_seconds: float


@dataclass(frozen=True)
class ClipAnalysis:
    """Everything measured about a clip, kept for later tuning.

    Attributes:
        duration_seconds: Clip length.
        peak_dbfs: Loudest sample, in dB relative to full scale.
        rms_dbfs: Average loudness over the whole clip.
        frame_levels_dbfs: Loudness of each short frame (see ``frame_seconds``).
        pauses: Quiet stretches long enough to separate turns.
        turns: Speech windows to transcribe, one per turn.
        parameters: The settings used, so results can be reproduced.
    """

    duration_seconds: float
    peak_dbfs: float
    rms_dbfs: float
    frame_levels_dbfs: list[float]
    pauses: list[Pause]
    turns: list[TurnWindow]
    parameters: dict[str, float]


def read_mono_wav(path: Path) -> WavAudio:
    """Load a mono 16-bit PCM WAV file.

    Args:
        path: WAV file to read.

    Returns:
        The decoded audio.

    Raises:
        UnsupportedAudioError: If the file is not mono 16-bit PCM.
    """
    with wave.open(str(path), "rb") as wav_file:
        if wav_file.getnchannels() != constants.AUDIO_CHANNEL_COUNT:
            raise UnsupportedAudioError("WAV must be mono")
        if wav_file.getsampwidth() != constants.WAV_SAMPLE_WIDTH_BYTES:
            raise UnsupportedAudioError("WAV must be 16-bit")
        sample_rate_hz = wav_file.getframerate()
        frame_bytes = wav_file.readframes(wav_file.getnframes())
    samples = array.array("h")
    samples.frombytes(frame_bytes)
    if sys.byteorder == "big":
        samples.byteswap()
    return WavAudio(samples=samples, sample_rate_hz=sample_rate_hz)


def write_wav_segment(audio: WavAudio, start_seconds: float, end_seconds: float, destination: Path) -> None:
    """Write part of an audio clip to a new WAV file.

    Args:
        audio: Source audio.
        start_seconds: Start of the segment.
        end_seconds: End of the segment.
        destination: WAV file to create.
    """
    first = max(0, int(start_seconds * audio.sample_rate_hz))
    last = min(len(audio.samples), int(end_seconds * audio.sample_rate_hz))
    segment = array.array("h", audio.samples[first:last])
    if sys.byteorder == "big":
        segment.byteswap()
    with wave.open(str(destination), "wb") as wav_file:
        wav_file.setnchannels(constants.AUDIO_CHANNEL_COUNT)
        wav_file.setsampwidth(constants.WAV_SAMPLE_WIDTH_BYTES)
        wav_file.setframerate(audio.sample_rate_hz)
        wav_file.writeframes(segment.tobytes())


def _amplitude_to_dbfs(amplitude: float) -> float:
    """Convert a sample amplitude (0 to full scale) to dB relative to full scale."""
    if amplitude <= 0:
        return constants.DBFS_FLOOR
    return max(constants.DBFS_FLOOR, 20.0 * math.log10(amplitude / constants.FULL_SCALE_AMPLITUDE))


def compute_frame_levels_dbfs(audio: WavAudio, frame_seconds: float) -> list[float]:
    """Measure loudness (RMS) of consecutive short frames.

    Args:
        audio: Audio to measure.
        frame_seconds: Length of each frame.

    Returns:
        One dBFS value per frame; the last frame may be shorter.
    """
    frame_length = max(1, round(audio.sample_rate_hz * frame_seconds))
    levels: list[float] = []
    for start in range(0, len(audio.samples), frame_length):
        frame = audio.samples[start:start + frame_length]
        mean_square = sum(sample * sample for sample in frame) / len(frame)
        levels.append(_amplitude_to_dbfs(math.sqrt(mean_square)))
    return levels


def find_pauses(
    frame_levels_dbfs: list[float],
    frame_seconds: float,
    silence_dbfs: float,
    min_pause_seconds: float,
) -> list[Pause]:
    """Find runs of quiet frames that last long enough to count as pauses.

    Leading and trailing quiet stretches are included.

    Args:
        frame_levels_dbfs: Per-frame loudness from ``compute_frame_levels_dbfs``.
        frame_seconds: Length of each frame.
        silence_dbfs: Frames quieter than this are "quiet".
        min_pause_seconds: Shortest quiet run that counts as a pause.

    Returns:
        Pauses in time order.
    """
    pauses: list[Pause] = []
    run_start: int | None = None
    for index, level in enumerate([*frame_levels_dbfs, None]):
        is_quiet = level is not None and level < silence_dbfs
        if is_quiet and run_start is None:
            run_start = index
        elif not is_quiet and run_start is not None:
            run_seconds = (index - run_start) * frame_seconds
            if run_seconds >= min_pause_seconds:
                pauses.append(Pause(run_start * frame_seconds, index * frame_seconds))
            run_start = None
    return pauses


def plan_turns(
    duration_seconds: float,
    pauses: list[Pause],
    padding_seconds: float,
    min_turn_seconds: float,
) -> list[TurnWindow]:
    """Turn the stretches between pauses into padded windows to transcribe.

    Args:
        duration_seconds: Clip length.
        pauses: Pauses in time order.
        padding_seconds: Extra audio kept before and after each turn.
        min_turn_seconds: Speech regions shorter than this are dropped.

    Returns:
        One window per remaining speech region.
    """
    regions: list[tuple[float, float]] = []
    cursor = 0.0
    for pause in pauses:
        if pause.start_seconds > cursor:
            regions.append((cursor, pause.start_seconds))
        cursor = max(cursor, pause.end_seconds)
    if cursor < duration_seconds:
        regions.append((cursor, duration_seconds))

    return [
        TurnWindow(
            start_seconds=max(0.0, region_start - padding_seconds),
            end_seconds=min(duration_seconds, region_end + padding_seconds),
        )
        for region_start, region_end in regions
        if region_end - region_start >= min_turn_seconds
    ]


def analyze_clip(
    audio: WavAudio,
    frame_seconds: float = constants.LEVEL_FRAME_SECONDS,
    silence_dbfs: float = constants.SILENCE_DBFS,
    turn_gap_seconds: float = constants.TURN_GAP_SECONDS,
    padding_seconds: float = constants.TURN_PADDING_SECONDS,
    min_turn_seconds: float = constants.MIN_TURN_SECONDS,
) -> ClipAnalysis:
    """Measure a clip and plan its turns.

    Args:
        audio: Clip audio.
        frame_seconds: Length of each loudness frame.
        silence_dbfs: Frames quieter than this count as silence.
        turn_gap_seconds: Shortest silence that separates two turns.
        padding_seconds: Extra audio kept around each turn.
        min_turn_seconds: Shortest speech region worth transcribing.

    Returns:
        The measurements and planned turns.
    """
    levels = compute_frame_levels_dbfs(audio, frame_seconds)
    pauses = find_pauses(levels, frame_seconds, silence_dbfs, turn_gap_seconds)
    turns = plan_turns(audio.duration_seconds, pauses, padding_seconds, min_turn_seconds)

    peak_amplitude = max(max(audio.samples, default=0), -min(audio.samples, default=0))
    mean_square = sum(sample * sample for sample in audio.samples) / max(1, len(audio.samples))
    return ClipAnalysis(
        duration_seconds=audio.duration_seconds,
        peak_dbfs=_amplitude_to_dbfs(peak_amplitude),
        rms_dbfs=_amplitude_to_dbfs(math.sqrt(mean_square)),
        frame_levels_dbfs=[round(level, constants.LEVEL_DECIMAL_PLACES) for level in levels],
        pauses=pauses,
        turns=turns,
        parameters={
            "frame_seconds": frame_seconds,
            "silence_dbfs": silence_dbfs,
            "turn_gap_seconds": turn_gap_seconds,
            "padding_seconds": padding_seconds,
            "min_turn_seconds": min_turn_seconds,
        },
    )
