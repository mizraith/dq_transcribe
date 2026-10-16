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

# Two-pass transcription: a fast draft with the "base" model, then a second,
# more accurate pass with "small.en" over the same turns. The refine pass replaces
# the draft text unless the line was edited by hand. Both passes run in parallel.
# Refine status values reuse the clip status values above, plus "skipped" for
# clips with nothing to refine.
REFINE_STATUS_SKIPPED = "skipped"
REFINE_WORKER_THREAD_NAME = "refine-worker"
REFINE_WHISPER_MODEL_SIZE = "small.en"

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
WHISPER_THREAD_COUNT = 4  # threads for the fast (draft) pass
WHISPER_REFINE_MODEL_PATH = WHISPER_DIRECTORY / "models" / f"ggml-{REFINE_WHISPER_MODEL_SIZE}.bin"
WHISPER_REFINE_THREAD_COUNT = 4  # threads for the refine pass (runs at the same time as the fast pass)
# whisper-server keeps a model loaded between requests. Loading costs about 3 s
# (base) and 10 s (small.en) on the tablet, so the app runs one server per pass
# instead of starting whisper-cli for every turn. If whisper-server is missing,
# the app falls back to whisper-cli.
WHISPER_SERVER_PATH = WHISPER_LIBRARY_DIRECTORY / "whisper-server"
WHISPER_SERVER_HOST = "127.0.0.1"
WHISPER_DRAFT_SERVER_PORT = 8178
WHISPER_REFINE_SERVER_PORT = 8179
WHISPER_SERVER_INFERENCE_PATH = "/inference"
WHISPER_SERVER_RESPONSE_FORMAT = "verbose_json"
WHISPER_SERVER_STARTUP_TIMEOUT_SECONDS = 120
WHISPER_SERVER_READY_POLL_SECONDS = 0.5
WHISPER_SERVER_LOG_FILENAME_FORMAT = "whisper_server_{port}.log"
# The refine pass runs at lower CPU priority (Unix "nice" increment) so the fast
# draft pass is not slowed down when both run at once. 0 means normal priority.
WHISPER_REFINE_NICE_INCREMENT = 10
WHISPER_LANGUAGE = "en"
WHISPER_TIMEOUT_SECONDS = 300
WHISPER_LIBRARY_PATH_VARIABLE = "LD_LIBRARY_PATH"
WHISPER_JSON_SUFFIX = ".json"
# Domain vocabulary passed to whisper as its initial prompt (package data file, so
# it can be tuned without code changes). History, measured on the tablet:
# - one example number ("Event 12") leaked into an unclear transcript;
# - a word-only prompt ("Event, heat, lane.") made whisper DROP the numbers;
# - several varied example numbers worked best for both models (2026-10-14).
# Leaked numbers remain possible on unclear audio; the call parser flags and the
# admin reviews every DQ.
WHISPER_PROMPT_PATH = Path(__file__).parent / "data" / "whisper_prompt.txt"
# Suppress non-speech tokens such as "[Music]" or "[Gunshot]".
WHISPER_SUPPRESS_NON_SPEECH = True
# Leftover sound labels removed from the displayed text (the raw output keeps them):
# anything in [brackets], (parentheses) or *asterisks*.
NON_SPEECH_ANNOTATION_PATTERN = r"\[[^\]]*\]|\([^)]*\)|\*[^*]*\*"

# --- Local web interface ----------------------------------------------------
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8000
# Chrome treats localhost as a secure context, which microphone access requires.
SERVER_DISPLAY_HOST = "localhost"

ROUTE_HOME = "/"
ROUTE_MIC_TEST = "/mic-test"
ROUTE_APP_SCRIPT = "/app.js"
ROUTE_CAPTURE_WORKLET = "/capture_worklet.js"
ROUTE_DQ_SCRIPT = "/dq_view.js"
ROUTE_MEET_SCRIPT = "/meet_view.js"
ROUTE_UPLOAD_RECORDING = "/api/recordings"  # legacy mic test
ROUTE_CLIPS = "/api/clips"
CLIP_AUDIO_SUFFIX = "/audio"
CLIP_REPROCESS_SUFFIX = "/reprocess"
# Trash bin for clips: trash and restore are reversible; delete is permanent and
# only allowed for clips already in the trash.
CLIP_TRASH_SUFFIX = "/trash"
CLIP_RESTORE_SUFFIX = "/restore"
CLIP_DELETE_SUFFIX = "/delete"
# Query string for the clip list: ?view=trash lists trashed clips instead.
QUERY_KEY_VIEW = "view"
VIEW_TRASH = "trash"
ROUTE_UTTERANCES = "/api/utterances"
# Meets: GET lists meets and the active one; POST creates a meet and makes it active.
ROUTE_MEETS = "/api/meets"
MEET_ACTIVATE_SUFFIX = "/activate"  # POST /api/meets/<id>/activate (id 0 = no active meet)
MEET_ASSIGN_SUFFIX = "/assign"  # POST /api/meets/<id>/assign with {"clip_ids": [...]}
NO_MEET_ID = 0
REQUEST_KEY_MEET_NAME = "name"
REQUEST_KEY_MEET_START_DATE = "start_date"
REQUEST_KEY_CLIP_IDS = "clip_ids"
RESPONSE_KEY_MEETS = "meets"
RESPONSE_KEY_ACTIVE_MEET_ID = "active_meet_id"
RESPONSE_KEY_MEET_ID = "meet_id"
RESPONSE_KEY_COUNT = "count"
MAX_MEET_NAME_CHARS = 100
REQUEST_KEY_OFFICIALS = "officials"
MAX_MEET_OFFICIALS = 200
# Roles for a meet's officials roster (stated by the owner, 2026-10-14). A DQ's
# "official role" uses the same list, so picking an official from the roster
# copies their role.
MEET_ROSTER_ROLES = (
    "Stroke & Turn Judge", "Chief Judge", "Deck Referee", "Meet Referee", "Starter", "Relay Take-off Judge", "Admin Official",
)
MEET_START_DATE_FORMAT = "%Y-%m-%d"
SETTING_ACTIVE_MEET_ID = "active_meet_id"
# --- DQs -----------------------------------------------------------------------
DQ_STATE_CALLED = "called"
DQ_STATE_ACCEPTED = "accepted"
DQ_STATE_NOTIFIED = "notified"  # the coach has been told (slip handed over, or published)
DQ_STATE_DECLINED = "declined"
DQ_STATE_PROTESTED = "protested"  # a coach protested; the referee is deciding
DQ_STATE_UPHELD = "upheld"  # the DQ stands after a protest
DQ_STATE_OVERTURNED = "overturned"  # the DQ was overturned (kept for the paper trail, never deleted)
DQ_STATES = (
    DQ_STATE_CALLED, DQ_STATE_ACCEPTED, DQ_STATE_NOTIFIED, DQ_STATE_PROTESTED, DQ_STATE_UPHELD,
    DQ_STATE_OVERTURNED, DQ_STATE_DECLINED,
)
# States after the coach was told (an event counts as notified when all its DQs are in one of these).
DQ_STATES_AFTER_NOTIFICATION = (DQ_STATE_NOTIFIED, DQ_STATE_PROTESTED, DQ_STATE_UPHELD, DQ_STATE_OVERTURNED)
# Protests (rulebook 102.22.4): the window runs from the race; the call time stands in for the race time.
PROTEST_WINDOW_MINUTES = 30
MAX_PROTEST_CYCLES = 2  # stated by the owner; a setting, never a hard stop (late/over-limit protests need a reason)
# Who (or what) notified the coach.
NOTIFIED_BY_OPTIONS = (
    "Admin Official", "Chief Judge", "Deck Referee", "Meet Referee", "Printed slip", "HTML Publish", "SMS Push", "None Required",
)
# Who rules on a protest: the first protest usually goes to the Deck Referee, a second to the Meet Referee.
PROTEST_RULED_BY_OPTIONS = ("Deck Referee", "Meet Referee", "Review committee")
REQUEST_KEY_AT = "at"  # ISO time the state change happened (default: now), e.g. when a protest came in
REQUEST_KEY_EVENT = "event"
REQUEST_KEY_INCLUDE_NOT_READY = "include_not_ready"
ROUTE_DQ_FROM_UTTERANCE = "/api/dqs/from-utterance"  # POST {"utterance_id", "text"}: a DQ made by hand from a transcript line
REQUEST_KEY_UTTERANCE_ID = "utterance_id"
REQUEST_KEY_TEXT = "text"
RESPONSE_KEY_DQ_IDS = "dq_ids"
DQ_TRASH_SUFFIX = "/trash"  # POST /api/dqs/<id>/trash: move a DQ to the trash (a mistake; restorable)
DQ_RESTORE_SUFFIX = "/restore"  # POST /api/dqs/<id>/restore
MANUAL_DQ_NOTE_FORMAT = "Made by hand from: \u201c{text}\u201d"
# Officials roster from the Officials Sign-In app (format: ai_docs/officials_roster_format.md).
ROUTE_IMPORT_OFFICIALS = "/api/officials/import"  # POST the roster file (raw body) or {"url": ...}; returns what was read
OFFICIALS_SIGNIN_ROSTER_URL = "http://localhost:8010/roster.json"  # the sign-in app's active session
MAX_ROSTER_FILE_BYTES = 2 * 1024 * 1024
RESPONSE_KEY_OFFICIALS = "officials"
RESPONSE_KEY_SESSION = "session"
RESPONSE_KEY_WARNINGS = "warnings"
ROUTE_NOTIFY_EVENT = "/api/events/notify"  # POST {"event", "by", "include_not_ready"}
RESPONSE_KEY_NOTIFIED = "notified"
# Fields a DQ needs before the coach can be notified ("infraction" = at least one).
DQ_REQUIRED_FIELDS = ("event", "heat", "lane", "swimmer", "club", "official", "referee")
DQ_REQUIRED_INFRACTION = "infraction"
# What the DQ list shows and filters by: the stored state, with "accepted" split
# by whether the required information is filled in.
DQ_STATUS_CALLED = "called"
DQ_STATUS_INCOMPLETE = "incomplete"  # accepted, information still missing
DQ_STATUS_PENDING_NOTIFICATION = "pending_notification"  # accepted and complete; coach not told yet
DQ_STATUS_NOTIFIED = "notified"
DQ_STATUS_PROTESTED = "protested"
DQ_STATUS_UPHELD = "upheld"
DQ_STATUS_OVERTURNED = "overturned"
DQ_STATUS_DECLINED = "declined"
DQ_STATUS_LABELS = {  # in workflow order (the filter buttons use this order)
    DQ_STATUS_CALLED: "Called",
    DQ_STATUS_INCOMPLETE: "Incomplete",
    DQ_STATUS_PENDING_NOTIFICATION: "Pending notification",
    DQ_STATUS_NOTIFIED: "Notified",
    DQ_STATUS_PROTESTED: "Protested",
    DQ_STATUS_UPHELD: "Upheld",
    DQ_STATUS_OVERTURNED: "Overturned",
    DQ_STATUS_DECLINED: "Declined",
}
DQ_SOURCE_AUTO = "auto"  # created from a detected call
DQ_SOURCE_MANUAL = "manual"
EVIDENCE_ROLE_CALL = "call"
EVIDENCE_ROLE_ACKNOWLEDGMENT = "acknowledgment"
EVIDENCE_ROLES = (EVIDENCE_ROLE_CALL, EVIDENCE_ROLE_ACKNOWLEDGMENT)
RACE_PHASES = ("Start", "Swim", "Turn", "Finish")
# Editable DQ fields (text) and their maximum length.
DQ_TEXT_FIELDS = ("event", "heat", "lane", "relay_leg", "swimmer", "club", "official", "official_role", "chief_judge", "referee", "notes")
MAX_DQ_FIELD_CHARS = 200
OFFICIAL_ROLES = MEET_ROSTER_ROLES
ROUTE_DQS = "/api/dqs"  # GET list (active meet), POST create
DQ_STATE_SUFFIX = "/state"  # POST /api/dqs/<id>/state {"state", "by", "note"}
ROUTE_CANDIDATES = "/api/candidates"  # GET detected calls for the active meet
ROUTE_DISMISS_CANDIDATE = "/api/candidates/dismiss"  # POST {"candidate_key"}
ROUTE_DQ_CODES = "/api/dq-codes"  # GET the current slip's codes for the picker
RESPONSE_KEY_DQS = "dqs"
RESPONSE_KEY_DQ_ID = "dq_id"
RESPONSE_KEY_CANDIDATES = "candidates"
RESPONSE_KEY_CODES = "codes"
REQUEST_KEY_CANDIDATE_KEY = "candidate_key"
REQUEST_KEY_STATE = "state"
REQUEST_KEY_BY = "by"
REQUEST_KEY_NOTE = "note"
REQUEST_KEY_INFRACTIONS = "infractions"
REQUEST_KEY_EVIDENCE = "evidence"
# DQ slip code tables (versioned CSV files; see reference/README.md).
REFERENCE_DIRECTORY = Path(__file__).resolve().parents[2] / "reference"
DQ_CODES_FILENAME_FORMAT = "dq_codes_rev-{revision}.csv"
CURRENT_SLIP_REVISION = "2024-01"
# Short stroke tags shown on the one-tap code buttons ("2C BA ..."), by slip section.
SLIP_SECTION_ABBREVIATIONS = {
    "Butterfly": "BU", "Backstroke": "BA", "Breaststroke": "BR", "Freestyle": "FR",
    "Individual Medley": "IM", "Relays": "RE", "Miscellaneous": "GEN", "Article 105": "105",
}

# --- Meet Manager files (heat sheets, entries, the Hy-Tek database) -----------
# Loaded files are kept here (one copy each, never put in a meet archive: the
# meet's own computer already keeps them).
MEET_FILES_DIRECTORY = DATA_DIRECTORY / "meet_files"
MAX_MEET_FILE_BYTES = 80 * 1024 * 1024
MEET_FILE_DOWNLOAD_TIMEOUT_SECONDS = 60
ROUTE_MEET_FILE_SUFFIX = "/file"  # POST /api/meets/<id>/file?name=<filename> (raw body) or {"url": ...}
ROUTE_MEET_PROGRAM_SUFFIX = "/program"
MEET_ARCHIVE_SUFFIX = "/archive"  # GET /api/meets/<id>/archive: the meet's archive zip (no Meet Manager files)
MEET_CLOSE_SUFFIX = "/close"  # POST: close the meet (unlocks emptying its trash)
MEET_REOPEN_SUFFIX = "/reopen"  # POST: reopen a closed meet
MEET_EMPTY_TRASH_SUFFIX = "/empty-trash"  # POST: permanently delete a closed meet's trashed clips and declined DQs
ZIP_CONTENT_TYPE = "application/zip"
FILE_CHUNK_BYTES = 1024 * 1024
RESPONSE_KEY_DELETED_CLIPS = "deleted_clips"
RESPONSE_KEY_DELETED_DQS = "deleted_dqs"
MEET_STILL_OPEN_MESSAGE = "Permanent delete is only allowed after the meet: close the meet first (Meet setup)."  # GET /api/meets/<id>/program: active file summary and events
QUERY_KEY_FILENAME = "name"
REQUEST_KEY_URL = "url"
RESPONSE_KEY_PROGRAM = "program"
MEET_FILE_FORMAT_DATABASE = "meet_manager_database"  # Hy-Tek Meet Manager backup (.zip) or database (.mdb)
MEET_FILE_FORMAT_PDF = "pdf_report"  # a Meet Manager report printed to PDF (heat sheet, entries)
MEET_FILE_FORMAT_HTML = "html_report"  # a Meet Manager report saved as HTML
MEET_FILE_FORMAT_TEXT = "text_report"  # the same report as plain text
MEET_FILE_FORMAT_LABELS = {
    MEET_FILE_FORMAT_DATABASE: "Meet Manager database",
    MEET_FILE_FORMAT_PDF: "PDF report",
    MEET_FILE_FORMAT_HTML: "HTML report",
    MEET_FILE_FORMAT_TEXT: "Text report",
}
# External programs used to read some formats (Termux: pkg install poppler mdbtools).
PDF_TO_TEXT_COMMAND = "pdftotext"
MDB_EXPORT_COMMAND = "mdb-export"
MDB_TABLES_COMMAND = "mdb-tables"
EXTERNAL_COMMAND_TIMEOUT_SECONDS = 120
# How a swimmer's name is written on a DQ ("{first} {last}" or "{last}, {first}").
SWIMMER_NAME_FORMAT = "{first} {last}"
# Stroke names as used on the DQ slip (sections of the code table).
STROKE_BUTTERFLY = "Butterfly"
STROKE_BACKSTROKE = "Backstroke"
STROKE_BREASTSTROKE = "Breaststroke"
STROKE_FREESTYLE = "Freestyle"
STROKE_INDIVIDUAL_MEDLEY = "Individual Medley"
STROKE_MEDLEY_RELAY = "Medley Relay"
STROKE_FREESTYLE_RELAY = "Freestyle Relay"
# Strokes for which every swimmer swims one stroke (so slip codes can be chosen from it).
SINGLE_STROKES = (STROKE_BUTTERFLY, STROKE_BACKSTROKE, STROKE_BREASTSTROKE, STROKE_FREESTYLE)

# Recordings of a meet go in recordings/<start date>_<name>/<day>/ (name made file-safe).
MEET_FOLDER_FORMAT = "{start_date}_{slug}"
ROUTE_EXPORT = "/api/export"
ROUTE_TRANSCRIPT_TEXT = "/api/transcript.txt"

WEB_DIRECTORY_NAME = "web"
MIC_TEST_PAGE_FILENAME = "mic_test.html"
APP_PAGE_FILENAME = "app.html"
APP_SCRIPT_FILENAME = "app.js"
DQ_SCRIPT_FILENAME = "dq_view.js"
MEET_SCRIPT_FILENAME = "meet_view.js"
SLIP_PAGE_FILENAME = "dq_slip.html"
# Printable DQ slips: GET /slips?ids=3,4 (those DQs) or /slips?event=12 (an event of the active meet).
ROUTE_SLIPS = "/slips"
QUERY_KEY_IDS = "ids"
QUERY_KEY_EVENT = "event"
# Bundled fonts (web/fonts/), served at /fonts/<file>. The slip's names use an OFL script font.
ROUTE_FONTS = "/fonts/"
FONTS_DIRECTORY_NAME = "fonts"
SLIP_FONT_FILENAME = "dancing-script-latin-600-normal.woff2"
FONT_CONTENT_TYPE = "font/woff2"
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
# Owner preference: 12-hour clock (US standard) on all screens and printouts.
USE_12_HOUR_CLOCK = True
TRANSCRIPT_TIME_FORMAT = "%I:%M:%S %p"
CLOCK_FORMAT_12_HOUR = "%I:%M %p"

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
# Slider limits for the capture settings (sliders suit a touchscreen better than typing).
CAPTURE_LEVEL_SLIDER_MIN_DBFS = -80
CAPTURE_LEVEL_SLIDER_MAX_DBFS = -10
CAPTURE_LEVEL_SLIDER_STEP_DBFS = 1
CAPTURE_HANG_SLIDER_MIN_SECONDS = 1.0
CAPTURE_HANG_SLIDER_MAX_SECONDS = 10.0
CAPTURE_HANG_SLIDER_STEP_SECONDS = 0.5
CAPTURE_PREROLL_SECONDS = 1.0
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
# Clipping: samples at or above this amplitude (fraction of full scale). The
# tablet's wired-headset input limits at about 0.92 (-0.7 dBFS), so a check at
# 0.99 never fired even when the input was badly overdriven (measured 2026-10-14).
CLIPPING_AMPLITUDE = 0.89
# A chunk counts as clipped only if at least this many samples reach that level.
CLIPPING_MIN_SAMPLES = 3
# Too hot: a chunk louder than this (RMS) means the input is overdriven even if it
# does not clip. Overdriven radio speech measured -6 to -9 dBFS; healthy speech is
# about -20 to -25 dBFS.
LEVEL_TOO_HOT_DBFS = -9.0
# The meter shades this range as the target for speech.
LEVEL_TARGET_LOW_DBFS = -30.0
LEVEL_TARGET_HIGH_DBFS = -12.0
# How long the "too loud" warning stays visible after the last loud chunk.
CLIPPING_WARNING_SECONDS = 3.0
# Downsampling to 16 kHz uses a windowed-sinc low-pass filter (instead of simple
# averaging, which folded high-frequency noise into the speech band).
DOWNSAMPLE_FILTER_HALF_WIDTH = 32  # input samples on each side of an output sample
DOWNSAMPLE_CUTOFF_FRACTION = 0.9  # cutoff as a fraction of the output Nyquist frequency
# Raw signal wanted: browser audio "enhancements" would distort radio audio.
CAPTURE_ECHO_CANCELLATION = False
CAPTURE_NOISE_SUPPRESSION = False
CAPTURE_AUTO_GAIN_CONTROL = False
CAPTURE_SETTINGS_STORAGE_KEY = "dq_transcribe_capture_settings"
# Browser storage key for the chosen audio input (microphone, headset jack, USB adapter).
AUDIO_INPUT_STORAGE_KEY = "dq_transcribe_audio_input"
UPLOAD_RETRY_SECONDS = 3

# If no audio chunk arrives for this long while capturing, the page warns and tries to recover.
CAPTURE_STALL_SECONDS = 4.0
CAPTURE_WATCHDOG_INTERVAL_SECONDS = 2.0
