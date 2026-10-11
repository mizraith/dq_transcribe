"""Speech-to-text backends for dq_transcribe.

The rest of the app depends only on the small ``Transcriber`` interface, so the
engine (currently whisper.cpp running locally) can be swapped without touching
the queue, database, or web code.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from dq_transcribe import constants

# whisper-cli command-line flags.
_FLAG_MODEL = "-m"
_FLAG_INPUT_FILE = "-f"
_FLAG_THREADS = "-t"
_FLAG_LANGUAGE = "-l"
_FLAG_NO_TIMESTAMPS = "-nt"
_FLAG_JSON_OUTPUT = "-oj"
_FLAG_OUTPUT_PREFIX = "-of"
_OUTPUT_PREFIX_NAME = "result"


class TranscriberUnavailableError(RuntimeError):
    """Raised when the speech engine or its model is not installed."""


class TranscriptionError(RuntimeError):
    """Raised when the speech engine ran but failed."""


@dataclass(frozen=True)
class TranscriptionResult:
    """Output of transcribing one audio file.

    Attributes:
        text: The transcript as plain text.
        raw_output: The engine's full output (JSON from whisper.cpp), kept for tuning.
    """

    text: str
    raw_output: str


class Transcriber(Protocol):
    """Anything that can turn a WAV file into text.

    Attributes:
        model_name: Name recorded with each result.
    """

    model_name: str

    def transcribe(self, wav_path: Path) -> TranscriptionResult:
        """Transcribe a 16 kHz mono WAV file.

        Args:
            wav_path: File to transcribe.

        Returns:
            The transcript and the engine's raw output.
        """
        ...


class WhisperCppTranscriber:
    """Runs the whisper.cpp command-line tool as a subprocess.

    Attributes:
        model_name: Model name recorded with each result.
    """

    def __init__(
        self,
        cli_path: Path = constants.WHISPER_CLI_PATH,
        model_path: Path = constants.WHISPER_MODEL_PATH,
        library_directory: Path = constants.WHISPER_LIBRARY_DIRECTORY,
        thread_count: int = constants.WHISPER_THREAD_COUNT,
        language: str = constants.WHISPER_LANGUAGE,
        timeout_seconds: float = constants.WHISPER_TIMEOUT_SECONDS,
    ) -> None:
        """Remember where whisper.cpp and its model live.

        Args:
            cli_path: The ``whisper-cli`` executable.
            model_path: A ggml model file.
            library_directory: Directory holding whisper.cpp's shared libraries.
            thread_count: CPU threads for transcription.
            language: Spoken language code, for example ``"en"``.
            timeout_seconds: Give up on a single file after this long.
        """
        self._cli_path = cli_path
        self._model_path = model_path
        self._library_directory = library_directory
        self._thread_count = thread_count
        self._language = language
        self._timeout_seconds = timeout_seconds
        self.model_name = model_path.stem

    def transcribe(self, wav_path: Path) -> TranscriptionResult:
        """Transcribe a 16 kHz mono WAV file with whisper.cpp.

        Args:
            wav_path: File to transcribe.

        Returns:
            The transcript (whitespace normalized) and whisper.cpp's JSON output.

        Raises:
            TranscriberUnavailableError: If whisper.cpp or the model is missing.
            TranscriptionError: If whisper.cpp fails or times out.
        """
        for required_path in (self._cli_path, self._model_path):
            if not required_path.exists():
                raise TranscriberUnavailableError(f"Missing {required_path}")

        environment = dict(os.environ)
        existing_library_path = environment.get(constants.WHISPER_LIBRARY_PATH_VARIABLE, "")
        environment[constants.WHISPER_LIBRARY_PATH_VARIABLE] = os.pathsep.join(
            part for part in (str(self._library_directory), existing_library_path) if part
        )

        with tempfile.TemporaryDirectory() as output_directory:
            output_prefix = Path(output_directory) / _OUTPUT_PREFIX_NAME
            command = [
                str(self._cli_path),
                _FLAG_MODEL, str(self._model_path),
                _FLAG_INPUT_FILE, str(wav_path),
                _FLAG_THREADS, str(self._thread_count),
                _FLAG_LANGUAGE, self._language,
                _FLAG_NO_TIMESTAMPS,
                _FLAG_JSON_OUTPUT,
                _FLAG_OUTPUT_PREFIX, str(output_prefix),
            ]
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=self._timeout_seconds,
                    env=environment,
                    check=False,
                )
            except subprocess.TimeoutExpired as error:
                raise TranscriptionError(f"whisper-cli timed out after {self._timeout_seconds} s") from error
            if completed.returncode != 0:
                raise TranscriptionError(
                    f"whisper-cli exited with {completed.returncode}: {completed.stderr.strip()[-500:]}"
                )
            json_path = output_prefix.with_suffix(constants.WHISPER_JSON_SUFFIX)
            raw_output = json_path.read_text(encoding="utf-8") if json_path.exists() else ""

        return TranscriptionResult(text=" ".join(completed.stdout.split()), raw_output=raw_output)
