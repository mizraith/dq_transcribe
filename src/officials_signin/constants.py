"""Central constants for officials_signin.

Every shared string, path component and tunable setting lives here, so that
refactoring means changing one line instead of hunting through the code.
Other modules import from this file rather than hard-coding values.

This app shares no code with dq_transcribe. The only contract between the two
is the officials roster file described in ``ai_docs/officials_roster_format.md``;
its keys and allowed values are defined in the "Roster file" section below.
"""

from pathlib import Path

# --- Application identity ---------------------------------------------------
APP_NAME = "officials_signin"
APP_TITLE = "Officials Sign-In"
COACHES_APP_TITLE = "Coaches Sign-In"  # the coaches page, same server and data

# --- Local storage ----------------------------------------------------------
DATA_DIRECTORY = Path.home() / f".{APP_NAME}"
DATABASE_FILENAME = "signin.db"
DATABASE_PATH = DATA_DIRECTORY / DATABASE_FILENAME
DATABASE_TIMEOUT_SECONDS = 30
SQLITE_JOURNAL_MODE = "WAL"

# --- Web server ---------------------------------------------------------------
# Loopback only: reachable from this device and nowhere else. dq_transcribe uses
# 8000 and its whisper servers 8178/8179, so this app uses 8010.
SERVER_HOST = "127.0.0.1"
SERVER_DISPLAY_HOST = "localhost"
SERVER_PORT = 8010

# --- Admin Assistant suite ----------------------------------------------------------
# This server is also the suite's home: the main page (launcher + meets) and the one
# list of meets and sessions that every app follows (owner, 2026-10-16). DQ Transcribe
# runs on its own port and reads/sets the current meet and session through the suite API.
SUITE_TITLE = "Admin Assistant"
DQ_TRANSCRIBE_TITLE = "DQ Transcribe"
DQ_TRANSCRIBE_PORT = 8000
DQ_TRANSCRIBE_PATH = "/"  # its main page
# Pages on these ports (any of the hosts below) may call the suite API from the browser.
SUITE_CLIENT_PORTS = (DQ_TRANSCRIBE_PORT,)
SUITE_CLIENT_HOSTS = ("localhost", "127.0.0.1")
ROUTE_SUITE_CURRENT = "/api/suite/current"  # GET: the meet, its sessions, the current session
ROUTE_SUITE_SELECT = "/api/suite/select"  # POST {meet_id?, session_id?}: make them current for every app
ROUTE_SUITE_MEETS = "/api/suite/meets"  # GET: every meet (for linking another app's records)
SUITE_ROUTES = (ROUTE_SUITE_CURRENT, ROUTE_SUITE_SELECT, ROUTE_SUITE_MEETS)
KEY_MEET_ID = "meet_id"
KEY_VERSION = "version"  # changes whenever the current meet, session or the meet's sessions change
KEY_SUITE = "suite"
ORIGIN_HEADER = "Origin"
CORS_ALLOW_ORIGIN_HEADER = "Access-Control-Allow-Origin"
CORS_ALLOW_CREDENTIALS_HEADER = "Access-Control-Allow-Credentials"
CORS_ALLOW_METHODS_HEADER = "Access-Control-Allow-Methods"
CORS_ALLOW_HEADERS_HEADER = "Access-Control-Allow-Headers"
CORS_ALLOWED_METHODS = "GET, POST, OPTIONS"
CORS_ALLOWED_HEADERS = "Content-Type"
VARY_HEADER = "Vary"
MAX_REQUEST_BODY_BYTES = 5_000_000  # room for one diagnostics frame
# The server restarts itself when its own Python code changes on disk (after a
# git pull), so the page and the server never disagree. Checked this often, and
# only after the change has been stable for one more check (no half-written pull).
CODE_RELOAD_CHECK_SECONDS = 3

WEB_DIRECTORY_NAME = "web"
VENDOR_DIRECTORY_NAME = "vendor"
PAGE_FILENAME = "signin.html"
SCRIPT_FILENAME = "signin.js"
CARD_SCANNER_SCRIPT_FILENAME = "card_scanner.js"
CARD_CAMERA_SCRIPT_FILENAME = "card_camera.js"
DESK_SHARED_SCRIPT_FILENAME = "desk_shared.js"

# Routes.
ROUTE_HOME = "/"  # the Admin Assistant main page (launcher + meets)
ROUTE_OFFICIALS_PAGE = "/officials"  # Officials Sign-In (was "/" before the main page existed)
ROUTE_HOME_SCRIPT = "/home.js"
ROUTE_MEETS_SCRIPT = "/meets.js"  # the meet overview and Meet setup (main page)
HOME_PAGE_FILENAME = "home.html"
HOME_SCRIPT_FILENAME = "home.js"
MEETS_SCRIPT_FILENAME = "meets.js"

ROUTE_COACHES = "/coaches"  # GET: the coaches sign-in page
# The apps on the main page's launcher and in every "Admin Assistant ›" menu. ``port`` is
# for an app served elsewhere (DQ Transcribe); ``tab`` names its browser tab so the
# launcher switches to it instead of opening another (and never reloads it).
HOME_APP_KEY = "home"
OFFICIALS_APP_KEY = "officials"
COACHES_APP_KEY = "coaches"
DQ_APP_KEY = "dq"
MEETS_MENU_LABEL = "Meets & Main Page"
HOME_TAB_NAME = "admin_assistant"
DQ_TAB_NAME = "dq_transcribe"  # DQ Transcribe names its own tab this (see its suite handoff)
OFFICIALS_TAB_NAME = "officials_signin"
COACHES_TAB_NAME = "coaches_signin"
SUITE_APPS = (
    {"key": HOME_APP_KEY, "title": SUITE_TITLE, "path": ROUTE_HOME, "port": None, "tab": HOME_TAB_NAME,
     "description": "Meets and sessions for every app, and this launcher."},
    {"key": DQ_APP_KEY, "title": DQ_TRANSCRIBE_TITLE, "path": DQ_TRANSCRIBE_PATH, "port": DQ_TRANSCRIBE_PORT, "tab": DQ_TAB_NAME,
     "description": "Records the officials' radio calls, finds the DQs and takes them to the coaches."},
    {"key": OFFICIALS_APP_KEY, "title": APP_TITLE, "path": ROUTE_OFFICIALS_PAGE, "port": None, "tab": OFFICIALS_TAB_NAME,
     "description": "Signs officials in from their USA Swimming card and builds the stroke & turn teams."},
    {"key": COACHES_APP_KEY, "title": COACHES_APP_TITLE, "path": ROUTE_COACHES, "port": None, "tab": COACHES_TAB_NAME,
     "description": "Signs coaches in from their USA Swimming card and marks the head coaches."},
)
ROUTE_SCRIPT = "/signin.js"
ROUTE_CARD_SCANNER_SCRIPT = "/card_scanner.js"
ROUTE_CARD_CAMERA_SCRIPT = "/card_camera.js"  # the camera window shared by the officials and coaches pages
ROUTE_DESK_SHARED_SCRIPT = "/desk_shared.js"  # LSC drop-down and club label, shared by both pages
ROUTE_VENDOR_PREFIX = "/vendor/"
ROUTE_STATE = "/api/state"  # GET: active meet, sessions, sign-ins
ROUTE_MEETS = "/api/meets"  # GET: every meet (Meet overview); POST: create a meet (and make it active)
ROUTE_MEET_PREFIX = "/api/meets/"  # POST /api/meets/<id>/open: make that meet the active one
MEET_OPEN_SUFFIX = "/open"
MEET_ARCHIVE_SUFFIX = "/archive"  # POST /api/meets/<id>/archive {archived: true|false}
MEET_DELETE_SUFFIX = "/delete"  # POST /api/meets/<id>/delete: an archived meet, its sessions and sign-ins
# GET /api/meets/<id>/zip (or ROUTE_MEET_ZIP for the open meet): the meet as a zip file
# (pages, CSV, rosters; never member IDs). See export.py.
MEET_ZIP_SUFFIX = "/zip"
ROUTE_MEET_ZIP = "/meet.zip"
MEET_ZIP_FILENAME_FORMAT = "{meet_slug}_{start_date}_officials_saved_{saved}.zip"
ZIP_CONTENT_TYPE = "application/zip"
KEY_SAVED_AT = "saved_at"
KEY_ARCHIVED = "archived"
# POST {id or null, name, start_date, sessions: [{id or null, name, date, ...}]}: create or
# change a meet and all its sessions at once (Meet setup's Save).
ROUTE_MEET_SAVE = "/api/meets/save"
MAX_SESSIONS_PER_MEET = 30
ROUTE_SESSIONS = "/api/sessions"  # POST: add a session to the active meet
ROUTE_SESSION_PREFIX = "/api/sessions/"  # POST /api/sessions/<id>: edit a session
SESSION_DELETE_SUFFIX = "/delete"  # POST /api/sessions/<id>/delete: delete it and its sign-ins
ROUTE_ACTIVE_SESSION = "/api/active-session"  # POST: choose the session being signed in
ROUTE_OFFICIALS = "/api/officials"  # GET: everyone known, for the name search
ROUTE_CARD_READING = "/api/card-reading"  # POST: OCR text from the camera -> parsed card
ROUTE_SIGNINS = "/api/signins"  # POST: sign an official in
ROUTE_SIGNIN_PREFIX = "/api/signins/"  # POST /api/signins/<id>/validate or /remove
SIGNIN_VALIDATE_SUFFIX = "/validate"
SIGNIN_REMOVE_SUFFIX = "/remove"
SIGNIN_EDIT_SUFFIX = "/edit"  # POST /api/signins/<id>/edit: fix name, years, roles, trainee
KEY_MERGED = "merged"  # how many duplicate official records an edit merged away
ROUTE_ROSTER = "/roster.json"
# Printable pages (server-rendered HTML with a print stylesheet).
# Session summaries with more rows than this print in smaller type (still one page).
PRINT_DENSE_ROW_COUNT = 40
ROUTE_PRINT_SESSION = "/print/session"  # ?session_id= (default: active session)
ROUTE_PRINT_MEET = "/print/meet"  # every session of the active meet, compact
ROUTE_TEAM_DISPLAY = "/teams/display"  # ?session_id=: big-screen teams + rotation, prints on one page
# "/officials?open=teams" opens the sign-in page straight on the Teams screen (the team page's
# "Back to Teams" link).
OPEN_QUERY_KEY = "open"
OPEN_TEAMS_VALUE = "teams"
ROUTE_PRINT_STYLESHEET = "/print.css"
ROUTE_DESK_STYLESHEET = "/desk.css"  # styles shared by the officials and coaches pages
DESK_STYLESHEET_FILENAME = "desk.css"
PRINT_STYLESHEET_FILENAME = "print.css"
ROUTE_ROSTER_DOWNLOAD = "/roster-download.json"

# Content types.
HTML_CONTENT_TYPE = "text/html; charset=utf-8"
JAVASCRIPT_CONTENT_TYPE = "text/javascript; charset=utf-8"
JSON_CONTENT_TYPE = "application/json"
CSS_CONTENT_TYPE = "text/css; charset=utf-8"
BINARY_CONTENT_TYPE = "application/octet-stream"
WASM_CONTENT_TYPE = "application/wasm"
CONTENT_TYPE_HEADER = "Content-Type"
CONTENT_LENGTH_HEADER = "Content-Length"
CONTENT_DISPOSITION_HEADER = "Content-Disposition"
CACHE_CONTROL_HEADER = "Cache-Control"
COOKIE_HEADER = "Cookie"
SET_COOKIE_HEADER = "Set-Cookie"
NO_CACHE = "no-store"
# The OCR engine files never change between commits, so the browser may keep them.
VENDOR_CACHE = "max-age=86400"
VENDOR_CONTENT_TYPE_BY_SUFFIX = {
    ".js": JAVASCRIPT_CONTENT_TYPE,
    ".wasm": WASM_CONTENT_TYPE,
    ".gz": BINARY_CONTENT_TYPE,
}

# --- JSON request and response keys ---------------------------------------------
KEY_ERROR = "error"
KEY_OK = "ok"
KEY_ID = "id"
KEY_NAME = "name"
KEY_START_DATE = "start_date"
KEY_DATE = "date"
KEY_START_TIME = "start_time"
KEY_SESSION_TYPE = "session_type"
KEY_OFFICIALS_MEETING_TIME = "officials_meeting_time"
KEY_SIGNIN_COUNT = "signin_count"
KEY_MEET = "meet"
KEY_SESSIONS = "sessions"
KEY_ACTIVE_SESSION_ID = "active_session_id"
KEY_SESSION_ID = "session_id"
KEY_SESSION_IDS = "session_ids"
KEY_SIGNINS = "signins"
KEY_OFFICIALS = "officials"
KEY_OFFICIAL_ID = "official_id"
KEY_TEXTS = "texts"
KEY_CARD = "card"
KEY_MATCH = "match"
KEY_ROLES = "roles"
KEY_ROLE = "role"  # one role per roster line
KEY_TRAINEE = "trainee"
KEY_CLUB = "club"
KEY_LSC = "lsc"
KEY_ZONE = "zone"
KEY_YEARS_CERTIFIED = "years_certified"
KEY_MEMBER_ID = "member_id"
KEY_VALIDATED = "validated"
KEY_VALIDATION_METHOD = "validation_method"
KEY_PROBLEMS = "problems"
KEY_TEAM = "team"
KEY_CARD_MEET_ID = "card_meet_id"  # meet where the official's card was last scanned

# --- Card reading (USA Swimming membership card, read by OCR in the browser) ----
# The browser runs Tesseract.js on camera frames and posts the text; the server
# parses it (card_reader.py) so the rules live in Python and are unit tested.
CARD_FIELD_NAME = "name"
CARD_FIELD_MEMBER_ID = "member_id"
CARD_FIELD_LSC = "lsc"
CARD_FIELD_CLUB = "club"
CARD_FIELD_GOOD_STANDING_UNTIL = "good_standing_until"
CARD_FIELD_EXPIRATION = "expiration_date"
CARD_FIELD_BACKGROUND_CHECK = "background_check_until"
CARD_FIELD_ATHLETE_PROTECTION = "athlete_protection_until"
CARD_FIELD_IS_OFFICIAL = "is_official"
# The green "In good standing" banner at the top of the card (white on teal, so
# OCR reads it less reliably than the dates; it is supporting evidence only).
CARD_FIELD_GOOD_STANDING_BANNER = "good_standing_banner"
CARD_FIELD_COMPLETE = "complete"
CARD_FIELD_MISSING = "missing"
CARD_FIELD_LABELS_FOUND = "labels_found"
CARD_FIELD_DATE_VOTES = "date_votes"
CARD_FIELD_NAME_VOTES = "name_votes"
# OCR can misread a digit (2027 read as 2021). A date that would send the official
# to the admin as expired must be read the same way this many times before the
# scanner stops; until then it keeps reading.
CARD_EXPIRED_DATE_CONFIRMATIONS = 2
# A new official's name must also be read the same way this many times (one blurry
# pass read "PAT" as "PAI" and "MARY"). A card that matches a known official by
# member ID needs no name confirmation: the stored name is used.
CARD_NAME_CONFIRMATIONS = 2

# Fields that must be read before the camera stops looking. The good-standing date
# may instead be covered by the green "In good standing" banner (see card_reader).
CARD_REQUIRED_FIELDS = (
    CARD_FIELD_NAME,
    CARD_FIELD_MEMBER_ID,
    CARD_FIELD_LSC,
    CARD_FIELD_CLUB,
    CARD_FIELD_GOOD_STANDING_UNTIL,
    CARD_FIELD_BACKGROUND_CHECK,
    CARD_FIELD_ATHLETE_PROTECTION,
)
# Short labels for the "read so far" chips shown while the camera is scanning.
CARD_FIELD_LABELS = {
    CARD_FIELD_NAME: "Name",
    CARD_FIELD_MEMBER_ID: "Member ID",
    CARD_FIELD_LSC: "LSC",
    CARD_FIELD_CLUB: "Club",
    CARD_FIELD_GOOD_STANDING_UNTIL: "Good standing",
    CARD_FIELD_BACKGROUND_CHECK: "Background check",
    CARD_FIELD_ATHLETE_PROTECTION: "Athlete protection",
}
# Dates that must not be in the past on the session date for automatic validation.
CARD_DATES_REQUIRED_CURRENT = {
    CARD_FIELD_GOOD_STANDING_UNTIL: "Membership (good standing)",
    CARD_FIELD_BACKGROUND_CHECK: "Background check",
    CARD_FIELD_ATHLETE_PROTECTION: "Athlete protection training",
}
# Label patterns tolerate common OCR slips ("Untii", "Standinq", "Backgrouncl").
CARD_DATE_LABEL_PATTERNS = {
    CARD_FIELD_GOOD_STANDING_UNTIL: r"good\s*stand\w*\s*un\w*",
    CARD_FIELD_EXPIRATION: r"expiration\s*date",
    CARD_FIELD_BACKGROUND_CHECK: r"back\w*\s*che\w*",
    CARD_FIELD_ATHLETE_PROTECTION: r"athlete\s*protect\w*\s*train\w*",
}
# Every dated row on the card, top to bottom. Used to pair labels with dates when
# OCR prints the label column and the date column separately.
CARD_DATE_ROW_PATTERNS = (
    (CARD_FIELD_GOOD_STANDING_UNTIL, CARD_DATE_LABEL_PATTERNS[CARD_FIELD_GOOD_STANDING_UNTIL]),
    (CARD_FIELD_EXPIRATION, CARD_DATE_LABEL_PATTERNS[CARD_FIELD_EXPIRATION]),
    (CARD_FIELD_BACKGROUND_CHECK, CARD_DATE_LABEL_PATTERNS[CARD_FIELD_BACKGROUND_CHECK]),
    (CARD_FIELD_ATHLETE_PROTECTION, CARD_DATE_LABEL_PATTERNS[CARD_FIELD_ATHLETE_PROTECTION]),
    (None, r"concussion"),
    (None, r"mandatory\s*report"),
)
# "Member Id" is often read as "Member ld", "Member Ia" or "Member 1d".
CARD_MEMBER_ID_LABEL_PATTERN = r"member\s*[il1|][dla1|]\b"
CARD_LSC_CLUB_LABEL_PATTERN = r"lsc\s*(?:&|and|8|%)?\s*club"
# "Official" sometimes loses its first letter ("fficial", "ficial").
CARD_OFFICIAL_PATTERN = r"(?:\bo?f|\b)ficial\b"
# Banner text only: "In good standing" NOT followed by "until" (that is the date row).
CARD_GOOD_STANDING_BANNER_PATTERN = r"in\s*good\s*standing(?!\s*until)"
# Member IDs seen so far are 14 letters/digits; allow some slack for other formats.
CARD_MEMBER_ID_MIN_LENGTH = 10
CARD_MEMBER_ID_MAX_LENGTH = 16
CARD_LSC_CODE_LENGTH = 2
CARD_CLUB_CODE_MAX_LENGTH = 8
CARD_DATE_INPUT_FORMAT = "%m/%d/%Y"
ISO_DATE_FORMAT = "%Y-%m-%d"
# A name line has no digits and needs at least this many words and this share of letters.
CARD_NAME_MIN_WORDS = 2
CARD_NAME_MIN_LETTER_SHARE = 0.75
# When voting on the name, each other reading that contains a candidate adds this
# much, so "Pat Sample" beats a one-off "Dil Pat Sample P" with stray letters.
CARD_NAME_CONTAINED_BONUS = 0.5
# Label lines are never names, even when OCR mangles their punctuation.
CARD_NON_NAME_WORDS = (
    "member", "club", "lsc", "standing", "expiration", "background", "athlete", "protection",
    "concussion", "mandatory", "membership", "certifications", "profile", "official", "swimming", "usa",
)

# Settings sent to the camera page. The scanner tries these Tesseract page
# segmentation modes in turn, one per frame, and flips frames that read backwards
# (front cameras and some camera apps mirror the image).
# Measured on the owner's camera photo: layout 6 reads every field in one pass;
# layout 4 reads rows that 6 sometimes splits. 11 added nothing, so it is dropped.
OCR_PAGE_SEGMENTATION_MODES = ("6", "4")
# Frames are read by several OCR workers in parallel, each taking the newest
# camera frame as soon as it is free ("snapshots processed as we go").
OCR_WORKER_COUNT = 2
# Start the second worker a little later so the two read different frames.
OCR_WORKER_STAGGER_MILLISECONDS = 400
# --- Still capture with a live guide ----------------------------------------------
# The camera window checks small preview frames several times a second (no OCR):
# is the whole phone screen in view, big enough, sharp, and held still? A coloured
# frame and a hint guide the official; once it has been good for a moment, a short
# burst of stills is taken and the sharpest are read by OCR.
GUIDE_ANALYSIS_WIDTH = 480  # preview frames are checked at this width (pixels)
GUIDE_INTERVAL_MILLISECONDS = 120
GUIDE_GOOD_CHECKS_TO_CAPTURE = 4  # about half a second of "good" before capturing
# The screen's long side must be at least this share of the frame's short side.
GUIDE_MIN_SCREEN_SHARE = 0.45
# The screen must stay this far (share of the frame) from every frame edge.
GUIDE_EDGE_MARGIN_SHARE = 0.01
# Sharpness score (contrast-normalised Laplacian energy) needed to capture. Measured on
# the tablet's rear camera (2026-10-15): sharp frames 42-116, blurry ones 2-27 (blurry
# captures at 12-21 could not be read).
GUIDE_MIN_SHARPNESS = 30.0
# The screen must fill at least this share of the view (a small bright patch that is
# not the phone once went green on the tablet).
GUIDE_MIN_SCREEN_AREA_SHARE = 0.15
# Mean brightness change between checks (0-255) above which the phone is "moving".
GUIDE_MAX_MOTION = 6.0
# Text-direction test (column change energy / row change energy) above which the
# phone is sideways. Measured: upright 0.2-0.6, sideways 4.8-20.
GUIDE_SIDEWAYS_RATIO = 1.0
# Measure text direction only in the middle of the screen (this share trimmed from each
# side), away from the phone's edges and header bar.
GUIDE_SIDEWAYS_INNER_TRIM = 0.2
# Which way up is a sideways phone? The app's dark header bar marks the top: compare
# the mean brightness of this share of the screen at each end.
GUIDE_HEADER_SHARE = 0.15
CAPTURE_BURST_FRAMES = 4
CAPTURE_BURST_INTERVAL_MILLISECONDS = 70
CAPTURE_STILLS_KEPT = 2
# The main still is a real photo at the camera's full resolution where the browser
# supports it (ImageCapture.takePhoto; it also focuses first): a video frame leaves
# the name only ~9 pixels tall when the phone is held at arm's length. Video frames
# are the backup. Give up on the photo after this long.
CAPTURE_PHOTO_TIMEOUT_MILLISECONDS = 3000
# Stills are cropped to the screen and scaled so the upright screen is this wide.
OCR_UPRIGHT_SCREEN_WIDTH = 1100  # name capitals ~22 px (Tesseract reads best at 20-40 px); larger is slower
OCR_MAX_UPSCALE = 2.0
GUIDE_STATE_NO_SCREEN = "no_screen"
GUIDE_STATE_EDGE = "edge"
GUIDE_STATE_TURN_SIDEWAYS = "turn_sideways"  # upright phone running off the top or bottom
GUIDE_STATE_SMALL = "small"
GUIDE_STATE_BLURRY = "blurry"
GUIDE_STATE_MOVING = "moving"
GUIDE_STATE_GOOD = "good"
GUIDE_STATE_READING = "reading"
GUIDE_STATE_RETRY = "retry"
GUIDE_MESSAGES = {
    GUIDE_STATE_NO_SCREEN: "Show the phone's Membership card to the camera",
    GUIDE_STATE_EDGE: "Move back a little: the whole screen must be in view",
    GUIDE_STATE_TURN_SIDEWAYS: "Turn the phone sideways so the whole screen fits",
    GUIDE_STATE_SMALL: "Move the phone closer",
    GUIDE_STATE_BLURRY: "Hold still: focusing",
    GUIDE_STATE_MOVING: "Hold still",
    GUIDE_STATE_GOOD: "Hold it there…",
    GUIDE_STATE_READING: "Got it: reading the card…",
    GUIDE_STATE_RETRY: "Could not read it all: hold it up again",
}
GUIDE_COLOURS = {
    GUIDE_STATE_NO_SCREEN: "#dc2626",
    GUIDE_STATE_EDGE: "#f59e0b",
    GUIDE_STATE_TURN_SIDEWAYS: "#f59e0b",
    GUIDE_STATE_SMALL: "#f59e0b",
    GUIDE_STATE_BLURRY: "#f59e0b",
    GUIDE_STATE_MOVING: "#f59e0b",
    GUIDE_STATE_GOOD: "#16a34a",
    GUIDE_STATE_READING: "#16a34a",
    GUIDE_STATE_RETRY: "#f59e0b",
}
GUIDE_FRAME_LINE_WIDTH = 6
# Diagnostics: log the guide's measurements this often while scanning.
GUIDE_DIAGNOSTICS_EVERY_CHECKS = 4

# Orientations tried, in order, until a frame shows card words: upright, phone turned
# left, phone turned right (sideways fits the wide camera frame better), and mirrored
# (some camera apps flip images). Each is (clockwise rotation in degrees, mirrored).
OCR_ORIENTATIONS = ((0, False), (90, False), (270, False), (0, True))
# Finding the phone screen: the frame is split into small square cells; a cell is
# "screen" when its bright pixels (the background behind any text) are nearly as bright
# as the brightest cells in view. Touching screen cells are grouped, and the group with
# the most text-like texture wins (a lit wall or a face is bright but smooth).
SCREEN_CELL_PIXELS = 8
SCREEN_CELL_BRIGHT_QUANTILE = 0.8  # a cell's "background" brightness
SCREEN_REFERENCE_QUANTILE = 0.97  # "brightest cells in view"
SCREEN_BRIGHT_RATIO = 0.8
SCREEN_TEXTURE_SPREAD = 12.0  # brightness standard deviation that marks a textured cell
SCREEN_PLAIN_CELL_WEIGHT = 0.25  # a plain bright cell counts this much toward a group's score
OCR_SCREEN_MIN_AREA_SHARE = 0.04  # smaller groups are not a phone screen
OCR_SCREEN_MARGIN_SHARE = 0.05  # generous: a tight crop cut off the date column on the tablet
# Once an orientation shows card words it is kept; after this many passes in a row
# without card words (the phone was turned or taken away) the search starts again.
OCR_ORIENTATION_UNLOCK_MISSES = 2
# Words that only appear on the card; a frame containing one is a card frame.
OCR_CARD_HINT_PATTERN = r"member|standing|background|athlete|club|expiration|official"
OCR_LANGUAGE = "eng"
OCR_CONTRAST_CUTOFF_FRACTION = 0.02  # share of darkest/lightest pixels clipped by auto-contrast
# Before OCR each still is turned into black and white by comparing every pixel with
# the mean of the square around it (adaptive threshold): the card's grey values survive
# even next to dark phone edges, which made Tesseract's own black/white step drop them.
OCR_THRESHOLD_WINDOW_PIXELS = 41
OCR_THRESHOLD_OFFSET = 12  # how much darker than its surroundings a pixel must be to be ink
OCR_MAX_FRAME_WIDTH_PIXELS = 1600  # larger frames are scaled down before OCR (speed)
OCR_GIVE_UP_SECONDS = 25  # after this, offer "Admin check" instead of waiting
# Tesseract.js is bundled under web/vendor/tesseract and served from localhost,
# so OCR works offline with no install beyond Python and Chrome (see the README there).
OCR_ENGINE_PATH = "/vendor/tesseract/"
OCR_LANGUAGE_DATA_PATH = OCR_ENGINE_PATH.rstrip("/")  # Tesseract.js wants no trailing slash here
OCR_ENGINE_SCRIPT_FILENAME = "tesseract.min.js"
OCR_WORKER_SCRIPT_FILENAME = "worker.min.js"
# One core build only (SIMD + LSTM, supported by every current Chrome) keeps the repo small.
OCR_CORE_SCRIPT_FILENAME = "tesseract-core-simd-lstm.wasm.js"

# --- Camera diagnostics (off unless ticked in the camera window) --------------------
# Saves what the camera saw so card reading can be tuned: raw frames (JPEG), the
# OCR text of each pass, timings, and the camera's own settings. These files show
# the card, including the member ID: use it with your own card, and delete the
# folder when done.
DIAGNOSTICS_DIRECTORY = DATA_DIRECTORY / "diagnostics"
ROUTE_DIAGNOSTICS = "/api/diagnostics"  # POST one record (camera info or one frame)
DIAGNOSTICS_STORAGE_KEY = "officials_signin.save_diagnostics"
DIAGNOSTICS_JPEG_QUALITY = 0.85
DIAGNOSTICS_MAX_FRAMES_PER_SCAN = 30
DIAGNOSTICS_MAX_IMAGE_BYTES = 3_000_000
KEY_SCAN_ID = "scan_id"
KEY_RECORD = "record"
KEY_IMAGE = "image"
DIAGNOSTICS_SCAN_ID_PATTERN = r"^[0-9]{8}T[0-9]{6}$"
DIAGNOSTICS_RECORD_FILENAME = "records.jsonl"
DIAGNOSTICS_FRAME_FILENAME_FORMAT = "frame_{number:03d}.jpg"
DATA_URL_JPEG_PREFIX = "data:image/jpeg;base64,"

# --- Validation methods (roster file values) -----------------------------------
VALIDATION_HOST_LIST = "host_list"
VALIDATION_CAMERA = "camera"
VALIDATION_VISUAL = "visual"
VALIDATION_NONE = "none"
VALIDATION_METHODS = (VALIDATION_HOST_LIST, VALIDATION_CAMERA, VALIDATION_VISUAL, VALIDATION_NONE)

# --- Roles ------------------------------------------------------------------
# Must match dq_transcribe's MEET_ROSTER_ROLES exactly (the roster file contract).
# If a role is added here, dq_transcribe needs the same change.
ROSTER_ROLES = (
    "Stroke & Turn Judge", "Chief Judge", "Deck Referee", "Meet Referee", "Starter", "Relay Take-off Judge", "Admin Official",
)
DEFAULT_ROLE = "Stroke & Turn Judge"
# Corner officials and the admin run the meet from the deck corners or the table: anyone
# signed in with one of these roles is never put on (or counted for) a stroke & turn
# team, even if they also ticked Stroke & Turn Judge (owner, 2026-10-16).
CORNER_ROLES = ("Chief Judge", "Deck Referee", "Meet Referee", "Starter", "Admin Official")

# --- Roster file (the contract with dq_transcribe) --------------------------------
ROSTER_FORMAT_NAME = "officials-roster"
ROSTER_FORMAT_VERSION = 1
ROSTER_KEY_FORMAT = "format"
ROSTER_KEY_VERSION = "version"
ROSTER_KEY_GENERATED_AT = "generated_at"
ROSTER_KEY_MEET = "meet"
ROSTER_KEY_SESSION = "session"
ROSTER_KEY_OFFICIALS = "officials"
ROSTER_KEY_SESSION_TYPE = "type"  # optional, added within version 1
ROSTER_DOWNLOAD_FILENAME_FORMAT = "officials_roster_{start_date}_{session_slug}.json"

# --- USA Swimming zones by LSC code -------------------------------------------
# 59 LSCs in four zones. Source: USA Swimming LSC zone map, as listed at
# https://community.swimstandards.com/topic/142 (checked 2026-10-15).
ZONE_EASTERN = "Eastern"
ZONE_SOUTHERN = "Southern"
ZONE_CENTRAL = "Central"
ZONE_WESTERN = "Western"
LSC_CODES_BY_ZONE = {
    ZONE_EASTERN: ("AD", "AM", "CT", "ME", "MD", "MR", "MA", "NE", "NJ", "NI", "PV", "VA"),
    ZONE_CENTRAL: ("AR", "IL", "IN", "IA", "LE", "MI", "MW", "MN", "MV", "ND", "OH", "OK", "OZ", "SD", "WI"),
    ZONE_SOUTHERN: ("BD", "FL", "FG", "GA", "GU", "KY", "LA", "MS", "NC", "NT", "SC", "ST", "SE", "WT", "WV"),
    ZONE_WESTERN: ("AK", "AZ", "CC", "CO", "IE", "MT", "NM", "OR", "PC", "PN", "SI", "SN", "SR", "CA", "UT", "WY", "HI"),
}
ZONE_BY_LSC_CODE = {code: zone for zone, codes in LSC_CODES_BY_ZONE.items() for code in codes}

# --- LSC names (Local Swimming Committees) ----------------------------------------
# Shown instead of zones (owner, 2026-10-16: only Pacific Swimming splits into zones;
# other LSCs do not, so the LSC is what matters). Codes and names from USA Swimming's
# "Local Swimming Committees & Zones" map
# (https://www.usaswimming.org/docs/default-source/governance/lsc-maps/lsc-zone-map.pdf,
# checked 2026-10-16); Maine (ME) and New England (NE) complete the 59. The card shows
# the code: "LSC & Club: PC - PASA".
LSC_NAMES = {
    "AD": "Adirondack Swimming", "AK": "Alaska Swimming", "AM": "Allegheny Mountain Swimming",
    "AR": "Arkansas Swimming", "AZ": "Arizona Swimming", "BD": "Border Swimming",
    "CA": "Southern California Swimming", "CC": "Central California Swimming", "CO": "Colorado Swimming",
    "CT": "Connecticut Swimming", "FG": "Florida Gold Coast Swimming", "FL": "Florida Swimming",
    "GA": "Georgia Swimming", "GU": "Gulf Swimming", "HI": "Hawaiian Swimming", "IA": "Iowa Swimming",
    "IE": "Inland Empire Swimming", "IL": "Illinois Swimming", "IN": "Indiana Swimming",
    "KY": "Kentucky Swimming", "LA": "Louisiana Swimming", "LE": "Lake Erie Swimming",
    "MA": "Middle Atlantic Swimming", "MD": "Maryland Swimming", "ME": "Maine Swimming",
    "MI": "Michigan Swimming", "MN": "Minnesota Swimming", "MR": "Metropolitan Swimming",
    "MS": "Mississippi Swimming", "MT": "Montana Swimming", "MV": "Missouri Valley Swimming",
    "MW": "Midwestern Swimming", "NC": "North Carolina Swimming", "ND": "North Dakota Swimming",
    "NE": "New England Swimming", "NI": "Niagara Swimming", "NJ": "New Jersey Swimming",
    "NM": "New Mexico Swimming", "NT": "North Texas Swimming", "OH": "Ohio Swimming",
    "OK": "Oklahoma Swimming", "OR": "Oregon Swimming", "OZ": "Ozark Swimming", "PC": "Pacific Swimming",
    "PN": "Pacific Northwest Swimming", "PV": "Potomac Valley Swimming", "SC": "South Carolina Swimming",
    "SD": "South Dakota Swimming", "SE": "Southeastern Swimming", "SI": "San Diego-Imperial Swimming",
    "SN": "Sierra Nevada Swimming", "SR": "Snake River Swimming", "ST": "South Texas Swimming",
    "UT": "Utah Swimming", "VA": "Virginia Swimming", "WI": "Wisconsin Swimming",
    "WT": "West Texas Swimming", "WV": "West Virginia Swimming", "WY": "Wyoming Swimming",
}
# The LSC this desk is in: pre-selected on the sign-in sheet when the card did not give one.
DEFAULT_LSC_CODE = "PC"
CLUB_MAX_LENGTH = 12

# --- Sessions ---------------------------------------------------------------------
# Choices for the session type drop-down; "Other…" lets the admin type their own.
SESSION_TYPES = ("Timed Finals", "Prelims", "Finals", "AM", "PM", "A", "B", "C")
SESSION_TYPE_OTHER_LABEL = "Other…"
SESSION_TYPE_MAX_LENGTH = 30
# Single-letter types read better in a name with a prefix: "Friday Session A".
SESSION_LETTER_TYPES = ("A", "B", "C")
SESSION_LETTER_PREFIX = "Session"
# The officials meeting is usually an hour before the session starts (editable).
OFFICIALS_MEETING_MINUTES_BEFORE_START = 60

# --- Teams ------------------------------------------------------------------------
# Stroke & turn judges are split into equal teams; two teams are on deck at a time
# (one at each end) while the others rest, rotating every 30 minutes.
TEAM_POOL_ROLE = "Stroke & Turn Judge"
TEAM_NAME_FORMAT = "Team {number}"
# Candidate team counts. The one leaving the fewest officials over wins; on a tie
# the larger count (shorter shifts: 30 on / 30 off). 3 teams is the minimum for
# breaks (60 on / 30 off); fewer judges than that make one team each.
TEAM_COUNT_CHOICES = (4, 3)
MIN_TEAMS_FOR_BREAKS = 3
ROTATION_MINUTES = 30
# Rotation schedule (owner's example, 4 teams: 8:00 S=1 T=3, 8:30 S=2 T=4, ...): the
# team coming on takes the end of the team going off. Sessions run this long unless
# the admin sets an "estimated length" in Meet setup.
DEFAULT_SESSION_MINUTES = 240
MAX_SESSION_MINUTES = 12 * 60
SESSION_LENGTH_STEP_MINUTES = 30
KEY_ESTIMATED_MINUTES = "estimated_minutes"
# How teams share the ends (owner, 2026-10-15). Fixed: each team always works the same
# end. Rotating: a team coming back on works the other end from last time.
ROTATION_FIXED_ENDS = "fixed"
ROTATION_ROTATING_ENDS = "rotating"
ROTATION_MODES = (ROTATION_FIXED_ENDS, ROTATION_ROTATING_ENDS)
ROTATION_MODE_LABELS = {ROTATION_FIXED_ENDS: "Fixed ends", ROTATION_ROTATING_ENDS: "Rotating ends"}
DEFAULT_ROTATION_MODE = ROTATION_FIXED_ENDS
KEY_ROTATION_MODE = "rotation_mode"
MINUTES_PER_HOUR = 60
HOURS_PER_HALF_DAY = 12
MINUTES_PER_DAY = 24 * MINUTES_PER_HOUR
KEY_ROTATION_SCHEDULE = "rotation_schedule"
KEY_TIME = "time"
KEY_START_END_TEAM = "start_team"
KEY_TURN_END_TEAM = "turn_team"
# Officials left over after equal teams get these jobs, most senior first
# (suggestions: the admin picks who really does them).
ASSIGNMENT_ACJ = "Assistant Chief Judge"
ASSIGNMENT_FIFTEEN_METER = "15 m"
ASSIGNMENT_RELIEF = "Relief"
LEFTOVER_ASSIGNMENT_ORDER = (ASSIGNMENT_ACJ, ASSIGNMENT_FIFTEEN_METER, ASSIGNMENT_RELIEF)
EXTRA_ASSIGNMENTS = LEFTOVER_ASSIGNMENT_ORDER
# Short labels for the job chips on the Teams screen ("Off the teams").
ASSIGNMENT_SHORT_LABELS = {ASSIGNMENT_ACJ: "ACJ", ASSIGNMENT_FIFTEEN_METER: "15 m", ASSIGNMENT_RELIEF: "Relief"}
# Officials with unknown years certified sort after everyone with years.
UNKNOWN_YEARS_SORT_VALUE = -1
DEFAULT_LANES = 8
LANE_CHOICES = (6, 8, 10)
MIN_LANES = 1
MAX_LANES = 12
KEY_TEAMS = "teams"
KEY_LANES = "lanes"
KEY_TEAM_COUNT = "team_count"
KEY_FIFTEEN_METER_ON_TEAMS = "fifteen_meter_on_teams"
KEY_ASSIGNMENT = "assignment"
KEY_TEAM_LEAD = "team_lead"
KEY_MENTOR_SIGNIN_ID = "mentor_signin_id"
KEY_MENTOR = "mentor"  # roster file: the mentor's name, for trainees
KEY_SIGNIN_ID = "signin_id"
KEY_TEAM_SIZE = "team_size"
KEY_EXTRAS = "extras"
KEY_PATTERN = "pattern"
KEY_THIS_END = "this_end"
KEY_OTHER_END = "other_end"
# Team view (GET /api/teams) keys.
KEY_MEMBERS = "members"
KEY_JURISDICTION = "jurisdiction"
KEY_TRAINEES = "trainees"
KEY_LANE_CHOICES = "lane_choices"
KEY_JUDGE_COUNT = "judge_count"
KEY_PROPOSED_TEAM_COUNT = "proposed_team_count"
KEY_ALTERNATIVE_TEAM_COUNT = "alternative_team_count"
KEY_LAYOUTS = "layouts"
KEY_BUILT = "built"
KEY_UNPLACED = "unplaced"
KEY_UNPAIRED_TRAINEES = "unpaired_trainees"
KEY_ROTATION = "rotation"
KEY_EXTRA_ASSIGNMENTS = "extra_assignments"
KEY_AWAITING_CHECK = "awaiting_check"  # S&T sign-ins not checked yet (kept off the teams)
KEY_TEAM_POSITION = "team_position"  # order within a team (the admin can drag to reorder)
KEY_JURISDICTION_FLIPPED = "jurisdiction_flipped"  # start end gets the turn end's pattern
KEY_JURISDICTIONS = "jurisdictions"  # per team size: lanes at the start end and the turn end
KEY_START_END = "start_end"
KEY_TURN_END = "turn_end"
KEY_LANE_RANGE = "lane_range"
KEY_UNEVEN = "uneven"
KEY_LANE_JUDGE_COUNT = "lane_judge_count"  # team members with lanes (15 m excluded)
KEY_TEAMS_BUILT_AT = "teams_built_at"
LANE_PATTERN_SEPARATOR = "-"
LANE_PATTERN_ENDS_SEPARATOR = " / "
ROUTE_TEAMS = "/api/teams"  # GET: the team view for the active session
ROUTE_TEAMS_BUILD = "/api/teams/build"  # POST: build (or rebuild) teams automatically
ROUTE_TEAMS_SETTINGS = "/api/teams/settings"  # POST: lanes, rotation mode, 15 m on every team (no rebuild)
SIGNIN_TEAM_SUFFIX = "/team"  # POST /api/signins/<id>/team: move, lead, mentor
SIGNIN_SWAP_SUFFIX = "/swap"  # POST /api/signins/<id>/swap {with_signin_id}: swap two officials' places
KEY_WITH_SIGNIN_ID = "with_signin_id"

# --- Coaches sign-in (a separate page on this server, built in its own files) ----
# officials_signin/coaches.py, when present, handles these routes through
# coaches.handle_get / coaches.handle_post (see server._coaches_module).
COACHES_MODULE_NAME = "officials_signin.coaches"
ROUTE_COACHES_PREFIX = "/coaches/"  # GET: the coaches page's own files
ROUTE_COACHES_API_PREFIX = "/api/coaches/"  # GET/POST: the coaches page's API
# The two desk tabs tell each other when the meet, session or demo changed (see
# desk_shared.js); each also refreshes every so often while in view.
DESK_CHANNEL_NAME = "officials_signin_desk"
DESK_CHANGED_MESSAGE = "meet-or-session-changed"
DESK_REFRESH_SECONDS = 20
COACHES_PAGE_FILENAME = "coaches.html"
COACHES_SCRIPT_FILENAME = "coaches.js"
ROUTE_COACHES_SCRIPT = "/coaches/coaches.js"
ROUTE_COACHES_STATE = "/api/coaches/state"  # GET: meet, sessions (with coach counts), this session's coaches
ROUTE_COACHES_KNOWN = "/api/coaches/known"  # GET: every coach seen before, for the name search
ROUTE_COACHES_CARD_READING = "/api/coaches/card-reading"  # POST: OCR text -> card, check, known coach
ROUTE_COACHES_SIGNINS = "/api/coaches/signins"  # POST: sign a coach in to the session (and later ones)
ROUTE_COACH_SIGNIN_PREFIX = "/api/coaches/signins/"  # POST .../<id>/validate | /remove | /edit | /head
COACH_HEAD_SUFFIX = "/head"  # POST {head_coach: true|false}
ROUTE_COACHES_PRINT_SESSION = "/coaches/print/session"  # GET ?session_id=: the coaches of a session, by club
ROUTE_COACHES_PRINT_MEET = "/coaches/print/meet"  # GET: every session's coaches, compact
KEY_COACH_ID = "coach_id"
KEY_COACHES = "coaches"
KEY_HEAD_COACH = "head_coach"
KEY_COACH_COUNT = "coach_count"
COACH_ROLE = "Coach"
# Demo: made-up coaches per club, and how many of them are head coaches.
DEMO_COACHES_PER_CLUB = (1, 3)
DEMO_HEAD_COACHES_PER_CLUB = (1, 2)
DEMO_COACH_NAME_POOL = 20  # made-up names set aside for demo coaches

# --- Settings table keys -------------------------------------------------------
SETTING_ACTIVE_MEET_ID = "active_meet_id"
SETTING_ACTIVE_SESSION_ID = "active_session_id"
# Kept in the demo database so "Reset demo" rebuilds the same size of demo.
SETTING_DEMO_SIZE = "demo_size"  # JSON: the per-session sizes the demo was built with

# --- Limits ---------------------------------------------------------------------
NAME_MAX_LENGTH = 80
SESSION_NAME_MAX_LENGTH = 40
MAX_YEARS_CERTIFIED = 70
OFFICIAL_SEARCH_LIMIT = 500
OCR_TEXTS_PER_REQUEST_LIMIT = 20
OCR_TEXT_MAX_LENGTH = 20_000
TIME_OF_DAY_PATTERN = r"^\d{2}:\d{2}$"
DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"

# --- Demo mode -----------------------------------------------------------------
# A separate database full of made-up officials for trying the whole workflow
# (sign-in list, exceptions, teams, printouts) without touching the real meet. It is
# switched on per browser with a cookie; dq_transcribe's roster fetch never sends it,
# so it always gets the real roster.
DEMO_DATABASE_FILENAME = "demo.db"
DEMO_DATABASE_PATH = DATA_DIRECTORY / DEMO_DATABASE_FILENAME
DEMO_COOKIE_NAME = "officials_signin_demo"
DEMO_COOKIE_ON = "1"
ROUTE_DEMO = "/demo"  # GET: the demo setup page
ROUTE_DEMO_START = "/api/demo/start"  # POST {judges, trainees, sessions, head officials}: fresh demo meet
ROUTE_DEMO_EXIT = "/api/demo/exit"  # POST: back to the real meet
ROUTE_DEMO_OPEN = "/api/demo/open"  # POST: switch to the demo meet (built with the defaults if there is none)
ROUTE_DEMO_RESET = "/api/demo/reset"  # POST: rebuild the demo meet (same size), erasing every change
DEMO_RESET_WARNING_SECONDS = 10  # the "Reset demo?" warning closes by itself after this
DEMO_PAGE_FILENAME = "demo.html"
KEY_DEMO = "demo"
KEY_DEMO_READY = "demo_ready"
KEY_MEETS = "meets"
KEY_ACTIVE_MEET_ID = "active_meet_id"
KEY_OFFICIAL_COUNT = "official_count"
KEY_TRAINEES_COUNT = "trainees"
KEY_SESSIONS_COUNT = "session_count"
KEY_JUDGES_COUNT = "judge_count"
KEY_CORNER_OFFICIALS = "corner_officials"
# Demo setup: per session, how many stroke & turn judges and trainees sign in, plus (for
# every session) the corner officials and the admin when that box is ticked.
DEMO_DEFAULT_JUDGES = 13
DEMO_DEFAULT_SESSIONS = 3
DEMO_DEFAULT_TRAINEES = 2
DEMO_MAX_JUDGES = 60
DEMO_MAX_TRAINEES = 10
DEMO_MAX_SESSIONS = 5
DEMO_MEET_NAME = "Demo Invitational"
# Sessions of a typical weekend meet: (day offset from the first day, type, start time).
DEMO_SESSION_PLAN = (
    (0, "PM", "13:00"),
    (1, "Prelims", "08:00"),
    (1, "Finals", "17:00"),
    (2, "Prelims", "08:00"),
    (2, "Finals", "17:00"),
)
# Added to every session when "corner officials" is ticked.
DEMO_SPECIAL_ROLES = CORNER_ROLES
# Years certified in the demo, as the owner sees real crews (2026-10-16): most stroke &
# turn judges have 1-3 years, it falls off quickly, very few reach 10, none above 15.
# Relative weights per number of years.
DEMO_YEARS_WEIGHTS = {
    1: 22, 2: 20, 3: 16, 4: 10, 5: 8, 6: 6, 7: 4.5, 8: 3.5, 9: 2.5, 10: 1.8,
    11: 1.3, 12: 1.0, 13: 0.7, 14: 0.5, 15: 0.3,
}
# Referees, starters and the chief judge come from the more experienced end.
DEMO_HEAD_OFFICIAL_MIN_YEARS = 5
DEMO_UNKNOWN_YEARS_SHARE = 0.1
# One stroke & turn judge in the first session is left "card not checked", so the admin
# queue (and the Teams warning) have something to show.
DEMO_NEEDS_ADMIN_COUNT = 1
DEMO_LSC_CODES = ("PC", "SN", "CC")
DEMO_CLUB_CODES = ("DMOA", "DMOB", "DMOC", "DMOD", "DMOE")
DEMO_FIRST_NAMES = (
    "Avery", "Blake", "Casey", "Dana", "Emery", "Finley", "Gray", "Harper", "Indy", "Jordan", "Kai", "Logan",
    "Morgan", "Noel", "Oakley", "Parker", "Quinn", "Riley", "Sage", "Taylor", "Uma", "Val", "Wren", "Xan",
    "Yael", "Zion", "Alex", "Brook", "Cameron", "Devon", "Ellis", "Frankie", "Hayden", "Jamie", "Kendall", "Lane",
)
DEMO_LAST_NAMES = (
    "Abbott", "Barnes", "Castillo", "Delgado", "Ellison", "Fischer", "Garrison", "Holloway", "Ibarra", "Jensen",
    "Kowalski", "Lindqvist", "Moreno", "Nakamura", "Okafor", "Petrov", "Quintero", "Ramsey", "Sorensen", "Tanaka",
    "Ulrich", "Vasquez", "Whitaker", "Yamada", "Zimmerman", "Ashford", "Brennan", "Calloway", "Draper", "Everly",
)
# Some officials go by a nickname, printed in quotes on the card: Pat "Skip" Sample.
DEMO_NICKNAMES = ("Red", "Skip", "Doc", "Ace", "Scout", "Sunny")
DEMO_NICKNAME_SHARE = 0.15

# --- Meet reports (main page, Current meet > Reports...) ---------------------------------
# Whole-meet printouts for the current meet, listed in the main page's Reports pop-up
# (owner, 2026-10-16). Add a report here (title, one line, route) and it appears there.
SUITE_REPORTS = (
    {"key": "officials_meet", "title": "Meet summary - officials",
     "description": "Every session's officials: roles, club, years and card checks.", "route": ROUTE_PRINT_MEET},
    {"key": "coaches_meet", "title": "Meet summary - coaches",
     "description": "Every session's coaches, with the head coaches marked.", "route": ROUTE_COACHES_PRINT_MEET},
)
