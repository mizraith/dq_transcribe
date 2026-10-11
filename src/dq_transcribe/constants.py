"""Central constants for dq_transcribe.

Every shared string, path component, and tunable setting lives here so that
refactoring means changing one line instead of hunting through the codebase.
Other modules must import from this file rather than hard-coding values.
"""

from pathlib import Path

# --- Application identity ---------------------------------------------------
APP_NAME = "dq_transcribe"

# --- Local storage ----------------------------------------------------------
DATA_DIRECTORY = Path.home() / f".{APP_NAME}"
DATABASE_FILENAME = "notes.db"
DATABASE_PATH = DATA_DIRECTORY / DATABASE_FILENAME
RECORDINGS_DIRECTORY = DATA_DIRECTORY / "recordings"
MODELS_DIRECTORY = DATA_DIRECTORY / "models"

# --- Audio capture ----------------------------------------------------------
# Whisper models expect 16 kHz mono audio.
AUDIO_SAMPLE_RATE_HZ = 16_000
AUDIO_CHANNEL_COUNT = 1
RECORDING_FILE_EXTENSION = ".wav"

# --- Transcription ----------------------------------------------------------
# Starting point only; tune after measuring speed on the target tablet.
DEFAULT_WHISPER_MODEL_SIZE = "base"

# --- Local web interface ----------------------------------------------------
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8000
