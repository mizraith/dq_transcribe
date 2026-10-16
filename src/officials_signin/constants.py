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

# Routes.
ROUTE_HOME = "/"
ROUTE_SCRIPT = "/signin.js"
ROUTE_CARD_SCANNER_SCRIPT = "/card_scanner.js"
ROUTE_VENDOR_PREFIX = "/vendor/"
ROUTE_STATE = "/api/state"  # GET: active meet, sessions, sign-ins
ROUTE_MEETS = "/api/meets"  # POST: create a meet (and make it active)
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
ROUTE_ROSTER = "/roster.json"
ROUTE_ROSTER_DOWNLOAD = "/roster-download.json"

# Content types.
HTML_CONTENT_TYPE = "text/html; charset=utf-8"
JAVASCRIPT_CONTENT_TYPE = "text/javascript; charset=utf-8"
JSON_CONTENT_TYPE = "application/json"
BINARY_CONTENT_TYPE = "application/octet-stream"
WASM_CONTENT_TYPE = "application/wasm"
CONTENT_TYPE_HEADER = "Content-Type"
CONTENT_LENGTH_HEADER = "Content-Length"
CONTENT_DISPOSITION_HEADER = "Content-Disposition"
CACHE_CONTROL_HEADER = "Cache-Control"
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
# OCR can misread a digit (2027 read as 2021). A date that would send the official
# to the admin as expired must be read the same way this many times before the
# scanner stops; until then it keeps reading.
CARD_EXPIRED_DATE_CONFIRMATIONS = 2

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
CARD_MEMBER_ID_LABEL_PATTERN = r"member\s*i[dl1|]"
CARD_LSC_CLUB_LABEL_PATTERN = r"lsc\s*(?:&|and|8|%)?\s*club"
CARD_OFFICIAL_PATTERN = r"\bofficial\b"
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
# much, so "Mark Byer" beats a one-off "Dil Mark Byer P" with stray letters.
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
# A frame with at least this many letters but no card label is probably mirrored;
# the next frames are flipped. Fewer letters means the phone is not in view yet.
OCR_MIRROR_MIN_LETTERS = 40
# Words that only appear on the card; a frame containing one is a card frame.
OCR_CARD_HINT_PATTERN = r"member|standing|background|athlete|club|expiration|official"
OCR_LANGUAGE = "eng"
OCR_CONTRAST_CUTOFF_FRACTION = 0.02  # share of darkest/lightest pixels clipped by auto-contrast
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
# Officials left over after equal teams get these jobs, most senior first
# (suggestions: the admin picks who really does them).
ASSIGNMENT_ACJ = "Assistant Chief Judge"
ASSIGNMENT_FIFTEEN_METER = "15 m"
ASSIGNMENT_RELIEF = "Relief"
LEFTOVER_ASSIGNMENT_ORDER = (ASSIGNMENT_ACJ, ASSIGNMENT_FIFTEEN_METER, ASSIGNMENT_RELIEF)
EXTRA_ASSIGNMENTS = LEFTOVER_ASSIGNMENT_ORDER
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
KEY_TEAMS_BUILT_AT = "teams_built_at"
LANE_PATTERN_SEPARATOR = "-"
LANE_PATTERN_ENDS_SEPARATOR = " / "
ROUTE_TEAMS = "/api/teams"  # GET: the team view for the active session
ROUTE_TEAMS_BUILD = "/api/teams/build"  # POST: build (or rebuild) teams automatically
ROUTE_TEAMS_SETTINGS = "/api/teams/settings"  # POST: lanes, 15 m on every team (no rebuild)
SIGNIN_TEAM_SUFFIX = "/team"  # POST /api/signins/<id>/team: move, lead, mentor

# --- Settings table keys -------------------------------------------------------
SETTING_ACTIVE_MEET_ID = "active_meet_id"
SETTING_ACTIVE_SESSION_ID = "active_session_id"

# --- Limits ---------------------------------------------------------------------
NAME_MAX_LENGTH = 80
SESSION_NAME_MAX_LENGTH = 40
MAX_YEARS_CERTIFIED = 70
OFFICIAL_SEARCH_LIMIT = 500
OCR_TEXTS_PER_REQUEST_LIMIT = 20
OCR_TEXT_MAX_LENGTH = 20_000
TIME_OF_DAY_PATTERN = r"^\d{2}:\d{2}$"
DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"
