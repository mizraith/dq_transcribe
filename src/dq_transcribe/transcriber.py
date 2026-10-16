"""Speech-to-text backends for dq_transcribe.

The rest of the app depends only on the small ``Transcriber`` interface, so the
engine (currently whisper.cpp running locally) can be swapped without touching
the queue, database, or web code.

Two whisper.cpp backends are provided:

* ``WhisperServerTranscriber`` (preferred) starts ``whisper-server`` once and keeps
  the model loaded, sending each turn over a local HTTP request.
* ``WhisperCppTranscriber`` runs ``whisper-cli`` for every file, reloading the
  model each time. It is the fallback when ``whisper-server`` is not installed.
"""

from __future__ import annotations

import json
import logging
import os
import re
import signal
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from dq_transcribe import constants
from dq_transcribe.text_normalization import normalize_spoken_numbers

LOGGER = logging.getLogger(__name__)

# whisper-cli command-line flags.
_FLAG_MODEL = "-m"
_FLAG_INPUT_FILE = "-f"
_FLAG_THREADS = "-t"
_FLAG_LANGUAGE = "-l"
_FLAG_NO_TIMESTAMPS = "-nt"
_FLAG_JSON_OUTPUT = "-oj"
_FLAG_OUTPUT_PREFIX = "-of"
_FLAG_PROMPT = "--prompt"
_FLAG_SUPPRESS_NON_SPEECH = "-sns"
_OUTPUT_PREFIX_NAME = "result"
# whisper-server command-line flags (beyond the shared ones above).
_FLAG_HOST = "--host"
_FLAG_PORT = "--port"
# whisper-server /inference form fields.
_FIELD_FILE = "file"
_FIELD_RESPONSE_FORMAT = "response_format"
_FIELD_TEMPERATURE = "temperature"
_RESPONSE_KEY_TEXT = "text"
_WAV_CONTENT_TYPE = "audio/wav"
_GREEDY_TEMPERATURE = "0.0"
_NON_SPEECH_ANNOTATION = re.compile(constants.NON_SPEECH_ANNOTATION_PATTERN)


def clean_transcript_text(text: str) -> str:
    """Remove sound labels such as "[Music]" or "*static*", normalize spaces, and
    write event/heat/lane numbers as digits (see ``text_normalization``).

    Args:
        text: Text as printed by whisper.

    Returns:
        The spoken words only, single-spaced.
    """
    return normalize_spoken_numbers(" ".join(_NON_SPEECH_ANNOTATION.sub(" ", text).split()))


def load_prompt(prompt_path: Path) -> str:
    """Read the whisper initial prompt, or return an empty string if there is none.

    Args:
        prompt_path: Text file holding the prompt.

    Returns:
        The prompt on one line.
    """
    try:
        return " ".join(prompt_path.read_text(encoding="utf-8").split())
    except OSError:
        return ""


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


def whisper_environment(library_directory: Path) -> dict[str, str]:
    """Environment for running whisper.cpp programs (adds its shared libraries to the search path).

    Args:
        library_directory: Directory holding whisper.cpp's shared libraries.

    Returns:
        A copy of the current environment with the library path extended.
    """
    environment = dict(os.environ)
    existing_library_path = environment.get(constants.WHISPER_LIBRARY_PATH_VARIABLE, "")
    environment[constants.WHISPER_LIBRARY_PATH_VARIABLE] = os.pathsep.join(
        part for part in (str(library_directory), existing_library_path) if part
    )
    return environment


def encode_multipart_form(fields: dict[str, str], file_field: str, filename: str, file_bytes: bytes) -> tuple[bytes, str]:
    """Build a multipart/form-data request body (standard library only).

    Args:
        fields: Plain form fields.
        file_field: Name of the file field.
        filename: File name sent with the file.
        file_bytes: File contents (sent as audio/wav).

    Returns:
        ``(body, content_type_header)``.
    """
    boundary = f"----dq-transcribe-{uuid.uuid4().hex}"
    lines: list[bytes] = []
    for name, value in fields.items():
        lines.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    lines.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
        f"Content-Type: {_WAV_CONTENT_TYPE}\r\n\r\n".encode()
    )
    lines.append(file_bytes)
    lines.append(f"\r\n--{boundary}--\r\n".encode())
    return b"".join(lines), f"multipart/form-data; boundary={boundary}"


def stop_leftover_servers(server_path: Path, port: int) -> int:
    """Kill any earlier ``whisper-server`` still holding ``port`` (for example after a crash).

    Linux only (reads ``/proc``); does nothing elsewhere.

    Args:
        server_path: The ``whisper-server`` executable.
        port: Port the leftover server would be using.

    Returns:
        How many processes were stopped.
    """
    proc_directory = Path("/proc")
    if not proc_directory.is_dir():
        return 0
    stopped = 0
    for entry in proc_directory.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            arguments = (entry / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        words = [argument.decode(errors="replace") for argument in arguments if argument]
        if words and Path(words[0]).name == server_path.name and str(port) in words and _FLAG_PORT in words:
            try:
                os.kill(int(entry.name), signal.SIGKILL)
                stopped += 1
            except OSError:
                pass
    return stopped


NICE_PROGRAM = "nice"
NICE_FLAG = "-n"


def lower_priority(pid: int, increment: int) -> None:
    """Lower a started process's CPU priority by ``increment`` (no-op for 0, or where unsupported).

    Done from the parent after the process started, never with ``preexec_fn``: running
    Python code in a child forked from a multi-threaded server can deadlock (2026-10-16:
    a forked child hung before starting whisper-server, never released port 8000 and kept
    the accurate pass from starting).
    """
    if not increment or not hasattr(os, "setpriority"):
        return
    try:
        os.setpriority(os.PRIO_PROCESS, pid, os.getpriority(os.PRIO_PROCESS, pid) + increment)
    except OSError as error:
        LOGGER.warning("Could not lower the priority of process %d: %s", pid, error)


def with_nice(command: list[str], increment: int) -> list[str]:
    """``command`` run through ``nice`` to lower its priority (as is if 0 or ``nice`` is missing)."""
    nice_path = shutil.which(NICE_PROGRAM) if increment else None
    return [nice_path, NICE_FLAG, str(increment), *command] if nice_path else command


class WhisperServerTranscriber:
    """Keeps a ``whisper-server`` process running with its model loaded.

    The server is started on first use (or with ``start``), restarted
    automatically if it stops, and shut down with ``stop``. It listens on the
    loopback address only.

    Attributes:
        model_name: Model name recorded with each result.
    """

    def __init__(
        self,
        port: int,
        server_path: Path = constants.WHISPER_SERVER_PATH,
        model_path: Path = constants.WHISPER_MODEL_PATH,
        library_directory: Path = constants.WHISPER_LIBRARY_DIRECTORY,
        thread_count: int = constants.WHISPER_THREAD_COUNT,
        language: str = constants.WHISPER_LANGUAGE,
        timeout_seconds: float = constants.WHISPER_TIMEOUT_SECONDS,
        prompt_path: Path = constants.WHISPER_PROMPT_PATH,
        suppress_non_speech: bool = constants.WHISPER_SUPPRESS_NON_SPEECH,
        nice_increment: int = 0,
        log_directory: Path = constants.DATA_DIRECTORY,
        startup_timeout_seconds: float = constants.WHISPER_SERVER_STARTUP_TIMEOUT_SECONDS,
    ) -> None:
        """Remember how to run the server (it is not started yet).

        Args:
            port: Local port for this server (each pass uses its own).
            server_path: The ``whisper-server`` executable.
            model_path: A ggml model file.
            library_directory: Directory holding whisper.cpp's shared libraries.
            thread_count: CPU threads for transcription.
            language: Spoken language code, for example ``"en"``.
            timeout_seconds: Give up on a single request after this long.
            prompt_path: Text file with domain vocabulary for whisper's initial prompt.
            suppress_non_speech: Ask whisper not to emit sound labels such as "[Music]".
            nice_increment: Lower the server's CPU priority by this much (Unix only; 0 = unchanged).
            log_directory: Folder for the server's log file.
            startup_timeout_seconds: How long to wait for the model to load.
        """
        self._port = port
        self._server_path = server_path
        self._model_path = model_path
        self._library_directory = library_directory
        self._thread_count = thread_count
        self._language = language
        self._timeout_seconds = timeout_seconds
        self._prompt = load_prompt(prompt_path)
        self._suppress_non_speech = suppress_non_speech
        self._nice_increment = nice_increment
        self._log_path = log_directory / constants.WHISPER_SERVER_LOG_FILENAME_FORMAT.format(port=port)
        self._startup_timeout_seconds = startup_timeout_seconds
        self._process: subprocess.Popen[bytes] | None = None
        self._lock = threading.Lock()
        self.model_name = model_path.stem

    @property
    def _url(self) -> str:
        return f"http://{constants.WHISPER_SERVER_HOST}:{self._port}{constants.WHISPER_SERVER_INFERENCE_PATH}"

    def start(self) -> None:
        """Start the server (if not running) and wait until its model is loaded.

        Raises:
            TranscriberUnavailableError: If the program or model is missing, or the server does not come up.
        """
        with self._lock:
            self._ensure_running()

    def stop(self) -> None:
        """Shut the server down."""
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                self._process.terminate()
                try:
                    self._process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._process.kill()
            self._process = None

    def transcribe(self, wav_path: Path) -> TranscriptionResult:
        """Transcribe a 16 kHz mono WAV file using the running server.

        Args:
            wav_path: File to transcribe.

        Returns:
            The transcript (sound labels removed) and the server's JSON reply.

        Raises:
            TranscriberUnavailableError: If the server cannot be started.
            TranscriptionError: If the request fails twice (the server is restarted in between).
        """
        body, content_type = encode_multipart_form(
            {_FIELD_RESPONSE_FORMAT: constants.WHISPER_SERVER_RESPONSE_FORMAT, _FIELD_TEMPERATURE: _GREEDY_TEMPERATURE},
            _FIELD_FILE,
            wav_path.name,
            wav_path.read_bytes(),
        )
        with self._lock:
            for attempt in (1, 2):
                self._ensure_running()
                request = urllib.request.Request(
                    self._url, data=body, headers={"Content-Type": content_type}, method="POST"
                )
                try:
                    with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                        raw_output = response.read().decode("utf-8")
                    text = json.loads(raw_output).get(_RESPONSE_KEY_TEXT, "")
                    return TranscriptionResult(text=clean_transcript_text(text), raw_output=raw_output)
                except (OSError, ValueError) as error:  # URLError is an OSError; bad JSON is a ValueError
                    LOGGER.warning("whisper-server on port %d failed (attempt %d): %s", self._port, attempt, error)
                    if attempt == 2:
                        raise TranscriptionError(f"whisper-server request failed: {error}") from error
                    self._restart()
        raise TranscriptionError("unreachable")  # pragma: no cover

    # --- Process management (call with the lock held) ---------------------------

    def _ensure_running(self) -> None:
        """Start the server if it is not running, and wait for it to accept connections."""
        if self._process is not None and self._process.poll() is None:
            return
        for required_path in (self._server_path, self._model_path):
            if not required_path.exists():
                raise TranscriberUnavailableError(f"Missing {required_path}")
        if stop_leftover_servers(self._server_path, self._port):
            LOGGER.info("Stopped a leftover whisper-server on port %d", self._port)
        command = [
            str(self._server_path),
            _FLAG_MODEL, str(self._model_path),
            _FLAG_THREADS, str(self._thread_count),
            _FLAG_LANGUAGE, self._language,
            _FLAG_HOST, constants.WHISPER_SERVER_HOST,
            _FLAG_PORT, str(self._port),
            _FLAG_NO_TIMESTAMPS,
        ]
        if self._suppress_non_speech:
            command.append(_FLAG_SUPPRESS_NON_SPEECH)
        if self._prompt:
            command.extend([_FLAG_PROMPT, self._prompt])
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        with self._log_path.open("ab") as log_file:
            self._process = subprocess.Popen(
                command,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env=whisper_environment(self._library_directory),
                cwd=str(self._server_path.parent),
                close_fds=True,
            )
        lower_priority(self._process.pid, self._nice_increment)
        LOGGER.info("Started whisper-server (%s) on port %d", self.model_name, self._port)
        self._wait_until_ready()

    def _wait_until_ready(self) -> None:
        """Wait until the server accepts connections (its model is loaded first)."""
        deadline = time.monotonic() + self._startup_timeout_seconds
        while time.monotonic() < deadline:
            if self._process is None or self._process.poll() is not None:
                raise TranscriberUnavailableError(f"whisper-server exited; see {self._log_path}")
            try:
                with socket.create_connection((constants.WHISPER_SERVER_HOST, self._port), timeout=1):
                    return
            except OSError:
                time.sleep(constants.WHISPER_SERVER_READY_POLL_SECONDS)
        raise TranscriberUnavailableError(f"whisper-server did not start within {self._startup_timeout_seconds} s")

    def _restart(self) -> None:
        """Kill the server so the next request starts a fresh one."""
        if self._process is not None and self._process.poll() is None:
            self._process.kill()
            self._process.wait()
        self._process = None



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
        prompt_path: Path = constants.WHISPER_PROMPT_PATH,
        suppress_non_speech: bool = constants.WHISPER_SUPPRESS_NON_SPEECH,
        nice_increment: int = 0,
    ) -> None:
        """Remember where whisper.cpp and its model live.

        Args:
            cli_path: The ``whisper-cli`` executable.
            model_path: A ggml model file.
            library_directory: Directory holding whisper.cpp's shared libraries.
            thread_count: CPU threads for transcription.
            language: Spoken language code, for example ``"en"``.
            timeout_seconds: Give up on a single file after this long.
            prompt_path: Text file with domain vocabulary for whisper's initial prompt.
            suppress_non_speech: Ask whisper not to emit sound labels such as "[Music]".
            nice_increment: Lower whisper's CPU priority by this much (Unix only; 0 = unchanged).
        """
        self._cli_path = cli_path
        self._model_path = model_path
        self._library_directory = library_directory
        self._thread_count = thread_count
        self._language = language
        self._timeout_seconds = timeout_seconds
        self._prompt = load_prompt(prompt_path)
        self._suppress_non_speech = suppress_non_speech
        self._nice_increment = nice_increment
        self.model_name = model_path.stem

    def transcribe(self, wav_path: Path) -> TranscriptionResult:
        """Transcribe a 16 kHz mono WAV file with whisper.cpp.

        Args:
            wav_path: File to transcribe.

        Returns:
            The transcript (sound labels removed, whitespace normalized) and
            whisper.cpp's JSON output (unchanged).

        Raises:
            TranscriberUnavailableError: If whisper.cpp or the model is missing.
            TranscriptionError: If whisper.cpp fails or times out.
        """
        for required_path in (self._cli_path, self._model_path):
            if not required_path.exists():
                raise TranscriberUnavailableError(f"Missing {required_path}")

        environment = whisper_environment(self._library_directory)

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
            if self._suppress_non_speech:
                command.append(_FLAG_SUPPRESS_NON_SPEECH)
            if self._prompt:
                command.extend([_FLAG_PROMPT, self._prompt])
            command = with_nice(command, self._nice_increment)
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

        return TranscriptionResult(text=clean_transcript_text(completed.stdout), raw_output=raw_output)
