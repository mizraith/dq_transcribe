"""Coaches Sign-In: the coaches' desk, beside the officials' one.

Coaches show the Membership card in the USA Swimming app; the tablet camera reads it
(the same card reader as officials) and the coach is added to the session's list.
There are no teams for coaches. Each coach has a **Head Coach** flag, off by default,
so the admin knows who to approach; a club can have several head coaches (head
age-group coach, head senior coach, several sites).

The page shares the meet and its sessions with Officials Sign-In (same database,
same active session, same demo mode); the meet is set up on the officials page.

Plugged into the officials server through ``handle_get`` / ``handle_post`` (see
``server._coaches_module``): ``/coaches`` (the page), ``/coaches/...`` (its script
and printouts) and ``/api/coaches/...`` (its API). Coaches are kept in their own
tables (``coaches``, ``coach_signins``) in the same SQLite file, created on first use.

As for officials, a coach's member ID is stored (to recognise them next time) but
never shown, logged, printed or exported.
"""

from __future__ import annotations

import json
import random
import string
import threading
from datetime import date
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from officials_signin import constants
from officials_signin.card_reader import CardReading, check_card, read_card
from officials_signin.database import Database, SigninError, Validation, name_key, not_checked_validation, utc_now_iso
from officials_signin.reports import render_coaches_meet, render_coaches_session

_WEB_DIRECTORY = Path(__file__).parent / "web"
_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS coaches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        name_key TEXT NOT NULL,
        member_id TEXT,
        lsc TEXT,
        club TEXT,
        card_json TEXT,
        card_meet_id INTEGER,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS coaches_member_id ON coaches(member_id)",
    "CREATE INDEX IF NOT EXISTS coaches_name_key ON coaches(name_key)",
    """
    CREATE TABLE IF NOT EXISTS coach_signins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        coach_id INTEGER NOT NULL REFERENCES coaches(id),
        head_coach INTEGER NOT NULL DEFAULT 0,
        validated INTEGER NOT NULL DEFAULT 0,
        validation_method TEXT NOT NULL,
        problems_json TEXT,
        signed_in_at TEXT NOT NULL,
        UNIQUE (session_id, coach_id)
    )
    """,
)
_SIGNIN_ACTIONS = (
    constants.SIGNIN_VALIDATE_SUFFIX, constants.SIGNIN_REMOVE_SUFFIX, constants.SIGNIN_EDIT_SUFFIX,
    constants.COACH_HEAD_SUFFIX,
)
_ready_databases: set[str] = set()
_ready_lock = threading.Lock()


# --- Storage --------------------------------------------------------------------------


def ensure_tables(database: Database) -> None:
    """Create the coaches tables in this database (once per file per process)."""
    key = str(database.path)
    with _ready_lock:
        if key in _ready_databases:
            return
        with database._connect() as connection:  # noqa: SLF001 (same package)
            for statement in _SCHEMA:
                connection.execute(statement)
        _ready_databases.add(key)


def forget_tables(database: Database) -> None:
    """Forget that a database has the tables (the demo database is rebuilt from scratch)."""
    with _ready_lock:
        _ready_databases.discard(str(database.path))


def _coach_summary(row: Any) -> dict[str, Any]:
    """Page-safe view of a coach row (no member ID)."""
    return {
        constants.KEY_ID: row["id"],
        constants.KEY_NAME: row["name"],
        constants.KEY_CLUB: row["club"],
        constants.KEY_LSC: row["lsc"],
        constants.KEY_ZONE: None if row["lsc"] is None else constants.ZONE_BY_LSC_CODE.get(row["lsc"]),
        constants.KEY_CARD_MEET_ID: row["card_meet_id"],
    }


def list_known_coaches(database: Database) -> list[dict[str, Any]]:
    """Every coach seen before, for the name search (member IDs left out)."""
    with database._connect() as connection:  # noqa: SLF001
        rows = connection.execute(
            "SELECT id, name, lsc, club, card_meet_id FROM coaches ORDER BY name COLLATE NOCASE LIMIT ?",
            (constants.OFFICIAL_SEARCH_LIMIT,),
        ).fetchall()
    return [_coach_summary(row) for row in rows]


def get_coach(database: Database, coach_id: int) -> dict[str, Any] | None:
    """One coach (page-safe), or None."""
    with database._connect() as connection:  # noqa: SLF001
        row = connection.execute("SELECT id, name, lsc, club, card_meet_id FROM coaches WHERE id = ?", (coach_id,)).fetchone()
    return None if row is None else _coach_summary(row)


def find_coach_for_card(database: Database, reading: CardReading) -> int | None:
    """A known coach matching a card: by member ID, else by name."""
    with database._connect() as connection:  # noqa: SLF001
        if reading.member_id:
            row = connection.execute(
                "SELECT id FROM coaches WHERE member_id = ? ORDER BY id LIMIT 1", (reading.member_id,)
            ).fetchone()
            if row is not None:
                return int(row["id"])
        if reading.name:
            row = connection.execute(
                "SELECT id FROM coaches WHERE name_key = ? ORDER BY id LIMIT 1", (name_key(reading.name),)
            ).fetchone()
            if row is not None:
                return int(row["id"])
    return None


def save_coach(
    database: Database,
    coach_id: int | None,
    name: str | None,
    club: str | None,
    reading: CardReading | None,
    meet_id: int | None,
) -> int:
    """Create or update a coach from the sign-in sheet and any card reading.

    The name on the sheet wins (the admin may have fixed an OCR slip); member ID,
    LSC and club from the card win over stored ones; a club typed on the sheet wins
    over everything (the admin's correction).

    Returns:
        The coach's ID.

    Raises:
        SigninError: For a new coach without a name, or an unknown ID.
    """
    chosen_name = (name or (reading.name if reading else None) or "").strip()[: constants.NAME_MAX_LENGTH]
    typed_club = (club or "").strip().upper()[:constants.CLUB_MAX_LENGTH] or None
    now = utc_now_iso()
    card_json = None if reading is None else json.dumps(reading.to_dict())
    with database._connect() as connection:  # noqa: SLF001
        if coach_id is None:
            if not chosen_name:
                raise SigninError("A name is needed")
            cursor = connection.execute(
                "INSERT INTO coaches (name, name_key, member_id, lsc, club, card_json, card_meet_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    chosen_name, name_key(chosen_name),
                    None if reading is None else reading.member_id,
                    None if reading is None else reading.lsc,
                    typed_club or (None if reading is None else reading.club),
                    card_json, None if reading is None else meet_id, now, now,
                ),
            )
            return int(cursor.lastrowid)
        row = connection.execute("SELECT * FROM coaches WHERE id = ?", (coach_id,)).fetchone()
        if row is None:
            raise SigninError("Unknown coach")
        updated_name = chosen_name or row["name"]
        connection.execute(
            "UPDATE coaches SET name = ?, name_key = ?, member_id = ?, lsc = ?, club = ?, card_json = ?, "
            "card_meet_id = ?, updated_at = ? WHERE id = ?",
            (
                updated_name, name_key(updated_name),
                reading.member_id if reading is not None and reading.member_id else row["member_id"],
                reading.lsc if reading is not None and reading.lsc else row["lsc"],
                typed_club or (reading.club if reading is not None and reading.club else row["club"]),
                card_json if card_json is not None else row["card_json"],
                meet_id if reading is not None else row["card_meet_id"],
                now, coach_id,
            ),
        )
    return coach_id


def _lsc_and_club(payload: dict[str, Any]) -> tuple[str | None, str | None] | None:
    """The LSC and club chosen on the sheet, or None when not sent (same rules as officials)."""
    from officials_signin.server import lsc_and_club_from_payload  # the server imports this module lazily

    return lsc_and_club_from_payload(payload)


def set_coach_club(database: Database, coach_id: int, lsc: str | None, club: str | None) -> None:
    """Store the LSC and club chosen on the sign-in sheet."""
    with database._connect() as connection:  # noqa: SLF001
        connection.execute("UPDATE coaches SET lsc = ?, club = ?, updated_at = ? WHERE id = ?", (lsc, club, utc_now_iso(), coach_id))


def stored_coach_validation(database: Database, coach_id: int, meet_id: int, session_date: date) -> Validation | None:
    """Reuse a card check made earlier at the same meet (no second scan for the afternoon)."""
    with database._connect() as connection:  # noqa: SLF001
        row = connection.execute("SELECT card_json, card_meet_id FROM coaches WHERE id = ?", (coach_id,)).fetchone()
    if row is None or row["card_json"] is None or row["card_meet_id"] != meet_id:
        return None
    stored = json.loads(row["card_json"])
    reading = CardReading(**{field: stored.get(field) for field in CardReading.__dataclass_fields__})
    result = check_card(reading, session_date)
    return Validation(result.validated, constants.VALIDATION_CAMERA, result.problems)


def sign_in_coach(
    database: Database, coach_id: int, session_ids: list[int], head_coach: bool, validations: dict[int, Validation]
) -> list[int]:
    """Sign a coach in to sessions (again is fine: the newest check and head flag win).

    Returns:
        The coach sign-in IDs, one per session.
    """
    now = utc_now_iso()
    signin_ids = []
    with database._connect() as connection:  # noqa: SLF001
        for session_id in session_ids:
            validation = validations[session_id]
            connection.execute(
                "INSERT INTO coach_signins (session_id, coach_id, head_coach, validated, validation_method, "
                "problems_json, signed_in_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(session_id, coach_id) DO UPDATE SET head_coach = excluded.head_coach, "
                "validated = MAX(validated, excluded.validated), "
                "validation_method = CASE WHEN validated THEN validation_method ELSE excluded.validation_method END, "
                "problems_json = CASE WHEN validated THEN problems_json ELSE excluded.problems_json END",
                (session_id, coach_id, int(head_coach), int(validation.validated), validation.method,
                 json.dumps(validation.problems), now),
            )
            row = connection.execute(
                "SELECT id FROM coach_signins WHERE session_id = ? AND coach_id = ?", (session_id, coach_id)
            ).fetchone()
            signin_ids.append(int(row["id"]))
    return signin_ids


def list_coach_signins(database: Database, session_id: int) -> list[dict[str, Any]]:
    """A session's coaches, newest first (member IDs left out)."""
    with database._connect() as connection:  # noqa: SLF001
        rows = connection.execute(
            "SELECT s.id, s.coach_id, s.head_coach, s.validated, s.validation_method, s.problems_json, "
            "c.name, c.lsc, c.club FROM coach_signins s JOIN coaches c ON c.id = s.coach_id "
            "WHERE s.session_id = ? ORDER BY s.signed_in_at DESC, s.id DESC",
            (session_id,),
        ).fetchall()
    return [
        {
            constants.KEY_ID: row["id"],
            constants.KEY_COACH_ID: row["coach_id"],
            constants.KEY_NAME: row["name"],
            constants.KEY_CLUB: row["club"],
            constants.KEY_LSC: row["lsc"],
            constants.KEY_ZONE: None if row["lsc"] is None else constants.ZONE_BY_LSC_CODE.get(row["lsc"]),
            constants.KEY_HEAD_COACH: bool(row["head_coach"]),
            constants.KEY_VALIDATED: bool(row["validated"]),
            constants.KEY_VALIDATION_METHOD: row["validation_method"],
            constants.KEY_PROBLEMS: json.loads(row["problems_json"] or "[]"),
        }
        for row in rows
    ]


def coach_counts(database: Database, meet_id: int) -> dict[int, int]:
    """How many coaches are signed in to each session of a meet."""
    with database._connect() as connection:  # noqa: SLF001
        rows = connection.execute(
            "SELECT s.id, COUNT(c.id) AS count FROM sessions s LEFT JOIN coach_signins c ON c.session_id = s.id "
            "WHERE s.meet_id = ? GROUP BY s.id",
            (meet_id,),
        ).fetchall()
    return {row["id"]: row["count"] for row in rows}


def _update_signin(database: Database, signin_id: int, sql: str, values: tuple[Any, ...]) -> bool:
    """Run one UPDATE/DELETE on a coach sign-in; True if it existed."""
    with database._connect() as connection:  # noqa: SLF001
        return connection.execute(sql, (*values, signin_id)).rowcount > 0


def set_head_coach(database: Database, signin_id: int, head_coach: bool) -> bool:
    """Mark a coach as a head coach (or not) for this session. Any number per club."""
    return _update_signin(database, signin_id, "UPDATE coach_signins SET head_coach = ? WHERE id = ?", (int(head_coach),))


def validate_visually(database: Database, signin_id: int) -> bool:
    """The admin looked at the card: "Looks good"."""
    return _update_signin(
        database, signin_id,
        "UPDATE coach_signins SET validated = 1, validation_method = ?, problems_json = '[]' WHERE id = ?",
        (constants.VALIDATION_VISUAL,),
    )


def remove_signin(database: Database, signin_id: int) -> bool:
    """Take a coach off this session's list (the coach stays known for next time)."""
    return _update_signin(database, signin_id, "DELETE FROM coach_signins WHERE id = ?", ())


def edit_signin(database: Database, signin_id: int, name: str, club: str | None, head_coach: bool) -> bool:
    """Fix a coach's name or club (everywhere) and the head coach flag (this session)."""
    clean_name = name.strip()[: constants.NAME_MAX_LENGTH]
    if not clean_name:
        raise SigninError("A name is needed")
    clean_club = (club or "").strip().upper()[:constants.CLUB_MAX_LENGTH] or None
    with database._connect() as connection:  # noqa: SLF001
        row = connection.execute("SELECT coach_id FROM coach_signins WHERE id = ?", (signin_id,)).fetchone()
        if row is None:
            return False
        connection.execute(
            "UPDATE coaches SET name = ?, name_key = ?, club = ?, updated_at = ? WHERE id = ?",
            (clean_name, name_key(clean_name), clean_club, utc_now_iso(), row["coach_id"]),
        )
        connection.execute("UPDATE coach_signins SET head_coach = ? WHERE id = ?", (int(head_coach), signin_id))
    return True


def seed_demo_coaches(database: Database, session_ids: list[int], names: list[str], generator: random.Random) -> None:
    """Made-up coaches for the demo meet: a few per club, some of them head coaches.

    Args:
        database: The demo database.
        session_ids: The demo sessions (every coach signs in to all of them).
        names: Made-up names to use (unused ones are fine).
        generator: Random source.
    """
    ensure_tables(database)
    names_left = iter(names)
    lsc = generator.choice(constants.DEMO_LSC_CODES)
    for club in constants.DEMO_CLUB_CODES:
        count = generator.randint(*constants.DEMO_COACHES_PER_CLUB)
        heads = min(count, generator.randint(*constants.DEMO_HEAD_COACHES_PER_CLUB))
        for index in range(count):
            name = next(names_left, None)
            if name is None:
                return
            coach_id = save_coach(database, None, name, club, None, None)
            with database._connect() as connection:  # noqa: SLF001
                connection.execute("UPDATE coaches SET lsc = ? WHERE id = ?", (lsc, coach_id))
            validation = Validation(True, constants.VALIDATION_CAMERA, [])
            sign_in_coach(database, coach_id, session_ids, index < heads, {session_id: validation for session_id in session_ids})


# --- Pages ------------------------------------------------------------------------------


def _render(filename: str, values: dict[str, str]) -> bytes:
    """Fill a web template (a ``string.Template`` file) with values."""
    template = string.Template((_WEB_DIRECTORY / filename).read_text("utf-8"))
    return template.substitute(values).encode("utf-8")


def web_config() -> dict[str, Any]:
    """The officials page's settings (card reader, keys, routes) plus the coaches' own."""
    from officials_signin.server import build_web_config  # the server imports this module lazily

    config = build_web_config()
    config["routes"].update({
        "coachesState": constants.ROUTE_COACHES_STATE,
        "coachesKnown": constants.ROUTE_COACHES_KNOWN,
        "coachesCardReading": constants.ROUTE_COACHES_CARD_READING,
        "coachesSignins": constants.ROUTE_COACHES_SIGNINS,
        "coachSigninPrefix": constants.ROUTE_COACH_SIGNIN_PREFIX,
        "headSuffix": constants.COACH_HEAD_SUFFIX,
        "coachesPrintSession": constants.ROUTE_COACHES_PRINT_SESSION,
        "coachesPrintMeet": constants.ROUTE_COACHES_PRINT_MEET,
        "officials": constants.ROUTE_HOME,
    })
    config["keys"].update({
        "coachId": constants.KEY_COACH_ID,
        "coaches": constants.KEY_COACHES,
        "headCoach": constants.KEY_HEAD_COACH,
        "coachCount": constants.KEY_COACH_COUNT,
    })
    return config


def render_page() -> bytes:
    """The coaches sign-in page."""
    return _render(constants.COACHES_PAGE_FILENAME, {
        "app_title": constants.COACHES_APP_TITLE,
        "desk_stylesheet_route": constants.ROUTE_DESK_STYLESHEET,
        "script_route": constants.ROUTE_COACHES_SCRIPT,
        "card_scanner_route": constants.ROUTE_CARD_SCANNER_SCRIPT,
        "card_camera_route": constants.ROUTE_CARD_CAMERA_SCRIPT,
        "desk_shared_route": constants.ROUTE_DESK_SHARED_SCRIPT,
        "engine_script_route": constants.OCR_ENGINE_PATH + constants.OCR_ENGINE_SCRIPT_FILENAME,
        "officials_route": constants.ROUTE_HOME,
    })


def render_script() -> bytes:
    """The coaches page script, with the settings embedded."""
    return _render(constants.COACHES_SCRIPT_FILENAME, {"config": json.dumps(web_config())})


# --- Requests ---------------------------------------------------------------------------


def _state(database: Database, in_demo: bool) -> dict[str, Any]:
    """Meet, sessions (with coach counts) and the active session's coaches."""
    state = database.get_state()
    meet = state[constants.KEY_MEET]
    counts = {} if meet is None else coach_counts(database, meet[constants.KEY_ID])
    sessions = [
        {**session, constants.KEY_COACH_COUNT: counts.get(session[constants.KEY_ID], 0)}
        for session in state[constants.KEY_SESSIONS]
    ]
    active = state[constants.KEY_ACTIVE_SESSION_ID]
    return {
        constants.KEY_DEMO: in_demo,
        constants.KEY_MEET: meet,
        constants.KEY_SESSIONS: sessions,
        constants.KEY_ACTIVE_SESSION_ID: active,
        constants.KEY_COACHES: [] if active is None else list_coach_signins(database, active),
    }


def _active(database: Database) -> tuple[dict[str, Any], dict[str, Any], dict[int, dict[str, Any]]]:
    """The meet, the active session and all sessions by ID; refuses when none is chosen."""
    state = database.get_state()
    if state[constants.KEY_MEET] is None or state[constants.KEY_ACTIVE_SESSION_ID] is None:
        raise SigninError("Set up the meet and choose a session first (on the officials page)")
    sessions = {session[constants.KEY_ID]: session for session in state[constants.KEY_SESSIONS]}
    return state[constants.KEY_MEET], sessions[state[constants.KEY_ACTIVE_SESSION_ID]], sessions


def _card_reading(database: Database, payload: dict[str, Any]) -> dict[str, Any]:
    """Parse OCR text from the camera (same reply shape as the officials page)."""
    texts = payload.get(constants.KEY_TEXTS)
    if not isinstance(texts, list) or not all(isinstance(text, str) for text in texts):
        raise SigninError("Expected a list of OCR texts")
    texts = [text[: constants.OCR_TEXT_MAX_LENGTH] for text in texts[-constants.OCR_TEXTS_PER_REQUEST_LIMIT:]]
    reading = read_card(texts)
    state = database.get_state()
    active = state[constants.KEY_ACTIVE_SESSION_ID]
    session_date = date.today()
    for session in state[constants.KEY_SESSIONS]:
        if session[constants.KEY_ID] == active:
            session_date = date.fromisoformat(session[constants.KEY_DATE])
    result = check_card(reading, session_date)
    coach_id = find_coach_for_card(database, reading)
    match = None if coach_id is None else get_coach(database, coach_id)
    card = reading.to_dict()  # as on the officials page: sent back with the sign-in, never shown
    if result.unconfirmed:
        card[constants.CARD_FIELD_COMPLETE] = False
    if match is None and reading.name is not None and reading.name_votes < constants.CARD_NAME_CONFIRMATIONS:
        card[constants.CARD_FIELD_COMPLETE] = False  # a new name must read the same twice
    return {
        constants.KEY_CARD: card,
        constants.KEY_VALIDATED: result.validated,
        constants.KEY_PROBLEMS: result.problems,
        constants.KEY_MATCH: match,
    }


def _sign_in(database: Database, payload: dict[str, Any]) -> dict[str, Any]:
    """Sign a coach in to the active session (and any later sessions picked).

    Returns:
        The reply: coach ID, sign-in IDs, and whether the active session's check passed.
    """
    meet, active, sessions = _active(database)
    requested = payload.get(constants.KEY_SESSION_IDS) or [active[constants.KEY_ID]]
    if not all(isinstance(session_id, int) and session_id in sessions for session_id in requested):
        raise SigninError("Unknown session")
    session_ids = list(dict.fromkeys([active[constants.KEY_ID], *requested]))
    coach_id = payload.get(constants.KEY_COACH_ID)
    if coach_id is not None and not isinstance(coach_id, int):
        raise SigninError("Unknown coach")
    card = payload.get(constants.KEY_CARD)
    reading = (
        CardReading(**{field: card.get(field) for field in CardReading.__dataclass_fields__ if field in card})
        if isinstance(card, dict) else None
    )
    if coach_id is None and reading is not None:
        coach_id = find_coach_for_card(database, reading)
    name = payload.get(constants.KEY_NAME)
    coach_id = save_coach(database, coach_id, name if isinstance(name, str) else None, None, reading, meet[constants.KEY_ID])
    chosen = _lsc_and_club(payload)
    if chosen is not None:
        set_coach_club(database, coach_id, *chosen)  # the admin's choice wins over the card
    validations: dict[int, Validation] = {}
    for session_id in session_ids:
        session_date = date.fromisoformat(sessions[session_id][constants.KEY_DATE])
        if reading is not None:
            result = check_card(reading, session_date)
            validations[session_id] = Validation(result.validated, constants.VALIDATION_CAMERA, result.problems)
        else:
            stored = stored_coach_validation(database, coach_id, meet[constants.KEY_ID], session_date)
            validations[session_id] = stored if stored is not None else not_checked_validation()
    signin_ids = sign_in_coach(database, coach_id, session_ids, bool(payload.get(constants.KEY_HEAD_COACH)), validations)
    active_check = validations[active[constants.KEY_ID]]
    return {
        constants.KEY_COACH_ID: coach_id,
        constants.KEY_SIGNINS: signin_ids,
        constants.KEY_VALIDATED: active_check.validated,
        constants.KEY_PROBLEMS: active_check.problems,
    }


def _print_page(handler: Any, path: str, query: str) -> None:
    """The coaches printouts: one session (by club) or the whole meet."""
    database = handler.database
    state = database.get_state()
    meet = state[constants.KEY_MEET]
    if meet is None:
        handler._send_json_error(HTTPStatus.NOT_FOUND, "No meet yet")  # noqa: SLF001
        return
    sessions = database.list_sessions(meet[constants.KEY_ID])
    if path == constants.ROUTE_COACHES_PRINT_MEET:
        pairs = [(session, list_coach_signins(database, session[constants.KEY_ID])) for session in sessions]
        body = render_coaches_meet(meet, pairs)
    else:
        requested = parse_qs(query).get(constants.KEY_SESSION_ID, [])
        session_id = int(requested[0]) if requested and requested[0].isdigit() else state[constants.KEY_ACTIVE_SESSION_ID]
        session = next((item for item in sessions if item[constants.KEY_ID] == session_id), None)
        if session is None:
            handler._send_json_error(HTTPStatus.NOT_FOUND, "No such session in the active meet")  # noqa: SLF001
            return
        body = render_coaches_session(meet, session, list_coach_signins(database, session_id))
    handler._send_bytes(HTTPStatus.OK, constants.HTML_CONTENT_TYPE, body)  # noqa: SLF001


def handle_get(handler: Any, path: str, query: str) -> bool:
    """Serve the coaches page, its script, printouts and state. False for an unknown path."""
    ensure_tables(handler.database)
    if path in (constants.ROUTE_COACHES, constants.ROUTE_COACHES_PREFIX):
        handler._send_bytes(HTTPStatus.OK, constants.HTML_CONTENT_TYPE, render_page())  # noqa: SLF001
    elif path == constants.ROUTE_COACHES_SCRIPT:
        handler._send_bytes(HTTPStatus.OK, constants.JAVASCRIPT_CONTENT_TYPE, render_script())  # noqa: SLF001
    elif path == constants.ROUTE_COACHES_STATE:
        handler._send_json(HTTPStatus.OK, _state(handler.database, handler.in_demo))  # noqa: SLF001
    elif path == constants.ROUTE_COACHES_KNOWN:
        handler._send_json(HTTPStatus.OK, {constants.KEY_COACHES: list_known_coaches(handler.database)})  # noqa: SLF001
    elif path in (constants.ROUTE_COACHES_PRINT_SESSION, constants.ROUTE_COACHES_PRINT_MEET):
        _print_page(handler, path, query)
    else:
        return False
    return True


def handle_post(handler: Any, path: str, payload: dict[str, Any]) -> bool:
    """Card readings, sign-ins and changes to a coach sign-in. False for an unknown path."""
    database = handler.database
    ensure_tables(database)
    if path == constants.ROUTE_COACHES_CARD_READING:
        handler._send_json(HTTPStatus.OK, _card_reading(database, payload))  # noqa: SLF001
        return True
    if path == constants.ROUTE_COACHES_SIGNINS:
        handler._send_json(HTTPStatus.OK, _sign_in(database, payload))  # noqa: SLF001
        return True
    if not path.startswith(constants.ROUTE_COACH_SIGNIN_PREFIX):
        return False
    rest = path[len(constants.ROUTE_COACH_SIGNIN_PREFIX):]
    action = next((suffix for suffix in _SIGNIN_ACTIONS if rest.endswith(suffix)), None)
    number = rest[: -len(action)] if action else ""
    if action is None or not number.isdigit():
        return False
    signin_id = int(number)
    if action == constants.SIGNIN_VALIDATE_SUFFIX:
        found = validate_visually(database, signin_id)
    elif action == constants.SIGNIN_REMOVE_SUFFIX:
        found = remove_signin(database, signin_id)
    elif action == constants.COACH_HEAD_SUFFIX:
        found = set_head_coach(database, signin_id, bool(payload.get(constants.KEY_HEAD_COACH)))
    else:
        name = payload.get(constants.KEY_NAME)
        club = payload.get(constants.KEY_CLUB)
        if not isinstance(name, str) or (club is not None and not isinstance(club, str)):
            raise SigninError("A name is needed")
        found = edit_signin(database, signin_id, name, club, bool(payload.get(constants.KEY_HEAD_COACH)))
        chosen = _lsc_and_club(payload)
        if found and chosen is not None:
            with database._connect() as connection:  # noqa: SLF001
                row = connection.execute("SELECT coach_id FROM coach_signins WHERE id = ?", (signin_id,)).fetchone()
            set_coach_club(database, row["coach_id"], *chosen)
    if not found:
        handler._send_json_error(HTTPStatus.NOT_FOUND, "Sign-in not found")  # noqa: SLF001
        return True
    handler._send_json(HTTPStatus.OK, {constants.KEY_OK: True})  # noqa: SLF001
    return True
