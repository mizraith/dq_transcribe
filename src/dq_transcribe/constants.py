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

# Browsers record in their own container format; map the media type the browser
# reports to a file extension. Converting to RECORDING_FILE_EXTENSION happens later.
AUDIO_EXTENSION_BY_MEDIA_TYPE = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/mp4": ".m4a",
    "audio/wav": ".wav",
}
UNKNOWN_AUDIO_EXTENSION = ".bin"
RECORDING_FILENAME_PREFIX = "recording"
RECORDING_TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S_%f"

# --- Transcription ----------------------------------------------------------
# Starting point only; tune after measuring speed on the target tablet.
DEFAULT_WHISPER_MODEL_SIZE = "base"

# --- Local web interface ----------------------------------------------------
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8000
# Chrome treats localhost as a secure context, which microphone access requires.
SERVER_DISPLAY_HOST = "localhost"

ROUTE_HOME = "/"
ROUTE_UPLOAD_RECORDING = "/api/recordings"

WEB_DIRECTORY_NAME = "web"
MIC_TEST_PAGE_FILENAME = "mic_test.html"
MIC_TEST_RECORD_SECONDS = 5

# Largest accepted upload, to keep a runaway client from filling storage.
MAX_UPLOAD_BYTES = 100 * 1024 * 1024

HTML_CONTENT_TYPE = "text/html; charset=utf-8"
JSON_CONTENT_TYPE = "application/json"
CONTENT_TYPE_HEADER = "Content-Type"
CONTENT_LENGTH_HEADER = "Content-Length"

# JSON keys shared by the server and the web page (substituted into the page).
RESPONSE_KEY_SAVED_AS = "saved_as"
RESPONSE_KEY_SIZE_BYTES = "size_bytes"
RESPONSE_KEY_ERROR = "error"
