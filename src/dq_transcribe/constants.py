"""Central constants for dq_transcribe.

Every shared string, path component, and tunable setting lives here so that
refactoring means changing one line instead of hunting through the codebase.
Other modules must import from this file rather than hard-coding values.

Values marked "starting guess" have not been tuned against real FRS radio
audio. The app stores raw measurements with every clip so they can be tuned
later and old clips reprocessed.
"""

from pathlib import Path

# --- Application identity ---------------------------------------------------
APP_NAME = "dq_transcribe"

# --- Local storage ----------------------------------------------------------
DATA_DIRECTORY = Path.home() / f".{APP_NAME}"
DATABASE_FILENAME = "notes.db"
DATABASE_PATH = DATA_DIRECTORY / DATABASE_FILENAME
DATABASE_TIMEOUT_SECONDS = 30
RECORDINGS_DIRECTORY = DATA_DIRECTORY / "recordings"
SCRATCH_DIRECTORY = DATA_DIRECTORY / "tmp"
MODELS_DIRECTORY = DATA_DIRECTORY / "models"

# --- Audio files ------------------------------------------------------------
# Whisper models expect 16 kHz mono audio.
AUDIO_SAMPLE_RATE_HZ = 16_000
AUDIO_CHANNEL_COUNT = 1
WAV_SAMPLE_WIDTH_BYTES = 2
FULL_SCALE_AMPLITUDE = 32768.0
RECORDING_FILE_EXTENSION = ".wav"

CLIP_FILENAME_PREFIX = "clip"
CLIP_FILE_EXTENSION = ".wav"
RECORDING_FILENAME_PREFIX = "recording"
RECORDING_TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S_%f"
# Clips are saved in one subdirectory per local calendar day, named like this.
DAY_DIRECTORY_FORMAT = "%Y-%m-%d"

# Legacy mic-test uploads keep the browser's own format; map media type to extension.
AUDIO_EXTENSION_BY_MEDIA_TYPE = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/mp4": ".m4a",
    "audio/wav": ".wav",
}
UNKNOWN_AUDIO_EXTENSION = ".bin"
WAV_MEDIA_TYPES = ("audio/wav", "audio/x-wav", "audio/wave")
WAV_UPLOAD_MEDIA_TYPE = "audio/wav"

# --- Clip processing states -------------------------------------------------
CLIP_STATUS_QUEUED = "queued"
CLIP_STATUS_PROCESSING = "processing"
CLIP_STATUS_DONE = "done"
CLIP_STATUS_FAILED = "failed"
WORKER_IDLE_POLL_SECONDS = 2.0
WORKER_THREAD_NAME = "transcription-worker"

# --- Turn detection (server side) -------------------------------------------
# Level measurements are taken in short frames; a "pause" is a run of quiet
# frames, and speech between pauses becomes one turn (one radio transmission).
LEVEL_FRAME_SECONDS = 0.1
DBFS_FLOOR = -100.0
SILENCE_DBFS = -45.0  # starting guess
TURN_GAP_SECONDS = 0.8  # starting guess; FRS call/response gaps are under 2 s
TURN_PADDING_SECONDS = 0.15  # extra audio kept around each turn
MIN_TURN_SECONDS = 0.4  # shorter bursts (squelch clicks) are skipped
LEVEL_DECIMAL_PLACES = 1

# --- Conversation grouping --------------------------------------------------
# Clips whose gap (end of one to start of the next) is shorter than this belong
# to one call/response group. Starting guess; grouping is computed on the fly,
# so changing it never requires reprocessing audio.
CONVERSATION_GAP_SECONDS = 5.0
TIMESTAMP_UTC_SUFFIX = "Z"
TIMESTAMP_UTC_OFFSET = "+00:00"

# --- Transcription (whisper.cpp) --------------------------------------------
DEFAULT_WHISPER_MODEL_SIZE = "base"
WHISPER_DIRECTORY = DATA_DIRECTORY / "whisper.cpp"
WHISPER_LIBRARY_DIRECTORY = WHISPER_DIRECTORY / "build" / "bin"
WHISPER_CLI_PATH = WHISPER_LIBRARY_DIRECTORY / "whisper-cli"
WHISPER_MODEL_PATH = WHISPER_DIRECTORY / "models" / f"ggml-{DEFAULT_WHISPER_MODEL_SIZE}.bin"
WHISPER_THREAD_COUNT = 4
WHISPER_LANGUAGE = "en"
WHISPER_TIMEOUT_SECONDS = 300
WHISPER_LIBRARY_PATH_VARIABLE = "LD_LIBRARY_PATH"
WHISPER_JSON_SUFFIX = ".json"

# --- Local web interface ----------------------------------------------------
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8000
# Chrome treats localhost as a secure context, which microphone access requires.
SERVER_DISPLAY_HOST = "localhost"

ROUTE_HOME = "/"
ROUTE_MIC_TEST = "/mic-test"
ROUTE_APP_SCRIPT = "/app.js"
ROUTE_CAPTURE_WORKLET = "/capture_worklet.js"
ROUTE_UPLOAD_RECORDING = "/api/recordings"  # legacy mic test
ROUTE_CLIPS = "/api/clips"
CLIP_AUDIO_SUFFIX = "/audio"
CLIP_REPROCESS_SUFFIX = "/reprocess"
ROUTE_UTTERANCES = "/api/utterances"
ROUTE_EXPORT = "/api/export"
ROUTE_TRANSCRIPT_TEXT = "/api/transcript.txt"

WEB_DIRECTORY_NAME = "web"
MIC_TEST_PAGE_FILENAME = "mic_test.html"
APP_PAGE_FILENAME = "app.html"
APP_SCRIPT_FILENAME = "app.js"
CAPTURE_WORKLET_FILENAME = "capture_worklet.js"
MIC_TEST_RECORD_SECONDS = 5

CLIP_LIST_LIMIT = 200
CLIP_LIST_POLL_SECONDS = 3
MAX_UTTERANCE_TEXT_CHARS = 10_000
MAX_CAPTURE_INFO_CHARS = 4_000
# Largest accepted upload, to keep a runaway client from filling storage.
MAX_UPLOAD_BYTES = 100 * 1024 * 1024

HTML_CONTENT_TYPE = "text/html; charset=utf-8"
JAVASCRIPT_CONTENT_TYPE = "text/javascript; charset=utf-8"
TEXT_CONTENT_TYPE = "text/plain; charset=utf-8"
JSON_CONTENT_TYPE = "application/json"
CONTENT_TYPE_HEADER = "Content-Type"
CONTENT_LENGTH_HEADER = "Content-Length"
CONTENT_DISPOSITION_HEADER = "Content-Disposition"
CAPTURE_INFO_HEADER = "X-Capture-Info"
TRANSCRIPT_DOWNLOAD_FILENAME = "transcript.txt"
EXPORT_DOWNLOAD_FILENAME = "dq_transcribe_export.json"
TRANSCRIPT_TIME_FORMAT = "%H:%M:%S"

# JSON keys shared by the server and the web pages.
RESPONSE_KEY_SAVED_AS = "saved_as"
RESPONSE_KEY_SIZE_BYTES = "size_bytes"
RESPONSE_KEY_ERROR = "error"
RESPONSE_KEY_CLIP_ID = "clip_id"
RESPONSE_KEY_CLIPS = "clips"
RESPONSE_KEY_OK = "ok"
REQUEST_KEY_TEXT = "text"

# --- Browser capture (sent to the web app as settings) ----------------------
# The browser listens continuously and cuts a clip when sound starts, ending it
# after the audio has stayed quiet for CAPTURE_HANG_SECONDS. All are starting
# guesses; the page lets you change the three most important ones live.
CAPTURE_START_DBFS = -40.0
CAPTURE_END_DBFS = -45.0
CAPTURE_HANG_SECONDS = 3.0
CAPTURE_PREROLL_SECONDS = 0.5
CAPTURE_TRAIL_SECONDS = 0.5
CAPTURE_MIN_CLIP_SECONDS = 0.8
CAPTURE_MAX_CLIP_SECONDS = 120.0
CAPTURE_START_CHUNKS = 2
CAPTURE_CHUNK_SAMPLES = 2048
CAPTURE_PROCESSOR_NAME = "capture-processor"
# Keys in the capture-info JSON the browser sends with each clip.
CAPTURE_INFO_KEY_STARTED_AT = "startedAt"
CAPTURE_INFO_KEY_ENDED_AT = "endedAt"
# The level meter on the page shows this range, in dB relative to full scale.
METER_FLOOR_DBFS = -80.0
# Raw signal wanted: browser audio "enhancements" would distort radio audio.
CAPTURE_ECHO_CANCELLATION = False
CAPTURE_NOISE_SUPPRESSION = False
CAPTURE_AUTO_GAIN_CONTROL = False
CAPTURE_SETTINGS_STORAGE_KEY = "dq_transcribe_capture_settings"
UPLOAD_RETRY_SECONDS = 3

# If no audio chunk arrives for this long while capturing, the page warns and tries to recover.
CAPTURE_STALL_SECONDS = 4.0
CAPTURE_WATCHDOG_INTERVAL_SECONDS = 2.0
