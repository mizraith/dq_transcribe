"""SQLite storage for officials_signin.

Holds everyone who has ever signed in (so returning officials are one tap),
the meets and their sessions, and each session's sign-ins. Uses only the
standard library. Each call opens its own short-lived connection, so one
``Database`` object is safe to share between web server threads.

Personal data: the USA Swimming member ID is stored so a returning official's
card can be matched, but it is never logged and the official list sent to the
page leaves it out.
"""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from officials_signin import constants
from officials_signin.card_reader import CardReading, check_card

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS officials (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        name_key TEXT NOT NULL,
        member_id TEXT,
        lsc TEXT,
        club TEXT,
        certified_since_year INTEGER,
        trainee INTEGER NOT NULL DEFAULT 0,
        last_roles_json TEXT,
        card_json TEXT,
        card_meet_id INTEGER,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS officials_member_id ON officials(member_id)",
    "CREATE INDEX IF NOT EXISTS officials_name_key ON officials(name_key)",
    """
    CREATE TABLE IF NOT EXISTS meets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        start_date TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        meet_id INTEGER NOT NULL REFERENCES meets(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        date TEXT NOT NULL,
        start_time TEXT,
        session_type TEXT,
        officials_meeting_time TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS signins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        official_id INTEGER NOT NULL REFERENCES officials(id),
        roles_json TEXT NOT NULL,
        trainee INTEGER NOT NULL DEFAULT 0,
        validated INTEGER NOT NULL DEFAULT 0,
        validation_method TEXT NOT NULL,
        problems_json TEXT,
        team TEXT,
        signed_in_at TEXT NOT NULL,
        UNIQUE (session_id, official_id)
    )
    """,
    "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)",
)

# Columns added after the first release; `initialize` adds them to older databases.
_ADDED_SESSION_COLUMNS = {"session_type": "TEXT", "officials_meeting_time": "TEXT"}

_NON_LETTERS = re.compile(r"[^a-z]+")
_NOT_CHECKED_PROBLEM = "Card not checked yet"


class SigninError(ValueError):
    """A request the database refuses, with a message fit to show the admin."""


@dataclass
class Validation:
    """The outcome of checking an official for one session.

    Attributes:
        validated: True when the official may work the session.
        method: One of ``constants.VALIDATION_METHODS``.
        problems: Reasons for the admin when not validated.
    """

    validated: bool
    method: str
    problems: list[str] = field(default_factory=list)


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def name_key(name: str) -> str:
    """Matching key for a name: lower-case letters only, nickname quotes ignored.

    ``Mark "Red" Byer`` and ``MARK RED BYER`` give the same key.
    """
    return _NON_LETTERS.sub("", name.lower())


def years_to_since_year(years_certified: int | None, today: date) -> int | None:
    """Store "years certified" as the year certification began, so it ages by itself."""
    return None if years_certified is None else today.year - years_certified


def since_year_to_years(certified_since_year: int | None, on_date: date) -> int | None:
    """Years certified on a date, from the stored starting year."""
    return None if certified_since_year is None else max(0, on_date.year - certified_since_year)


class Database:
    """Officials, meets, sessions and sign-ins in one SQLite file."""

    def __init__(self, path: Path) -> None:
        """Remember where the database lives (``initialize`` creates it).

        Args:
            path: SQLite file path. Its folder is created if missing.
        """
        self.path = path

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Open a connection, commit on success, roll back on error, always close."""
        connection = sqlite3.connect(self.path, timeout=constants.DATABASE_TIMEOUT_SECONDS)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        """Create the folder, the tables and WAL mode. Safe to call every start."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(f"PRAGMA journal_mode = {constants.SQLITE_JOURNAL_MODE}")
            for statement in _SCHEMA:
                connection.execute(statement)
            existing = {row["name"] for row in connection.execute("PRAGMA table_info(sessions)")}
            for column, column_type in _ADDED_SESSION_COLUMNS.items():
                if column not in existing:
                    connection.execute(f"ALTER TABLE sessions ADD COLUMN {column} {column_type}")

    # --- Settings ---------------------------------------------------------------

    def _get_setting_id(self, connection: sqlite3.Connection, key: str) -> int | None:
        """Read an integer setting, or None."""
        row = connection.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return None if row is None or row["value"] is None else int(row["value"])

    def _set_setting(self, connection: sqlite3.Connection, key: str, value: int | None) -> None:
        """Write (or clear) an integer setting."""
        connection.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, None if value is None else str(value)),
        )

    # --- Meets and sessions -------------------------------------------------------

    def create_meet(self, name: str, start_date: str) -> int:
        """Create a meet and make it the active one (no session chosen yet).

        Args:
            name: Meet name.
            start_date: ISO date of the first day.

        Returns:
            The new meet's ID.
        """
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO meets (name, start_date, created_at) VALUES (?, ?, ?)",
                (name, start_date, utc_now_iso()),
            )
            meet_id = int(cursor.lastrowid)
            self._set_setting(connection, constants.SETTING_ACTIVE_MEET_ID, meet_id)
            self._set_setting(connection, constants.SETTING_ACTIVE_SESSION_ID, None)
        return meet_id

    def add_session(
        self,
        name: str,
        session_date: str,
        start_time: str | None,
        session_type: str | None = None,
        officials_meeting_time: str | None = None,
    ) -> int:
        """Add a session to the active meet; it becomes active if none is.

        Args:
            name: Session name, for example ``Friday Prelims``.
            session_date: ISO date.
            start_time: ``HH:MM`` or None.
            session_type: For example ``Prelims`` (see ``constants.SESSION_TYPES``) or
                the admin's own text; None if not given.
            officials_meeting_time: ``HH:MM`` or None.

        Returns:
            The new session's ID.

        Raises:
            SigninError: If no meet is active.
        """
        with self._connect() as connection:
            meet_id = self._get_setting_id(connection, constants.SETTING_ACTIVE_MEET_ID)
            if meet_id is None:
                raise SigninError("Create a meet first")
            cursor = connection.execute(
                "INSERT INTO sessions (meet_id, name, date, start_time, session_type, officials_meeting_time) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (meet_id, name, session_date, start_time, session_type, officials_meeting_time),
            )
            session_id = int(cursor.lastrowid)
            if self._get_setting_id(connection, constants.SETTING_ACTIVE_SESSION_ID) is None:
                self._set_setting(connection, constants.SETTING_ACTIVE_SESSION_ID, session_id)
        return session_id

    def update_session(
        self,
        session_id: int,
        name: str,
        session_date: str,
        start_time: str | None,
        session_type: str | None,
        officials_meeting_time: str | None,
    ) -> None:
        """Change a session of the active meet (sign-ins are kept).

        Args: as for ``add_session``, plus the session's ID.

        Raises:
            SigninError: If the session is not part of the active meet.
        """
        with self._connect() as connection:
            meet_id = self._get_setting_id(connection, constants.SETTING_ACTIVE_MEET_ID)
            cursor = connection.execute(
                "UPDATE sessions SET name = ?, date = ?, start_time = ?, session_type = ?, officials_meeting_time = ? "
                "WHERE id = ? AND meet_id = ?",
                (name, session_date, start_time, session_type, officials_meeting_time, session_id, meet_id),
            )
            if cursor.rowcount == 0:
                raise SigninError("That session is not part of the active meet")

    def set_active_session(self, session_id: int) -> None:
        """Choose the session officials are signing in to.

        Raises:
            SigninError: If the session is not part of the active meet.
        """
        with self._connect() as connection:
            meet_id = self._get_setting_id(connection, constants.SETTING_ACTIVE_MEET_ID)
            row = connection.execute("SELECT meet_id FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if row is None or row["meet_id"] != meet_id:
                raise SigninError("That session is not part of the active meet")
            self._set_setting(connection, constants.SETTING_ACTIVE_SESSION_ID, session_id)

    def get_session(self, session_id: int) -> dict[str, Any] | None:
        """Return one session (with its meet ID), or None."""
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return None if row is None else dict(row)

    def get_state(self) -> dict[str, Any]:
        """Everything the sign-in page shows: the meet, its sessions and the active session's sign-ins.

        Returns:
            ``{"meet": ... or None, "sessions": [...], "active_session_id": ... or None,
            "signins": [...]}``. Sessions carry ``session_type``,
            ``officials_meeting_time`` and a ``signin_count``.
        """
        with self._connect() as connection:
            meet_id = self._get_setting_id(connection, constants.SETTING_ACTIVE_MEET_ID)
            active_session_id = self._get_setting_id(connection, constants.SETTING_ACTIVE_SESSION_ID)
            meet_row = None if meet_id is None else connection.execute(
                "SELECT id, name, start_date FROM meets WHERE id = ?", (meet_id,)
            ).fetchone()
            sessions = [
                dict(row)
                for row in connection.execute(
                    "SELECT s.id, s.name, s.date, s.start_time, s.session_type, s.officials_meeting_time, "
                    "(SELECT COUNT(*) FROM signins WHERE session_id = s.id) AS signin_count "
                    "FROM sessions s WHERE s.meet_id = ? ORDER BY s.date, s.start_time, s.id",
                    (meet_id,),
                )
            ]
        signins = [] if active_session_id is None else self.list_signins(active_session_id)
        return {
            constants.KEY_MEET: None if meet_row is None else dict(meet_row),
            constants.KEY_SESSIONS: sessions,
            constants.KEY_ACTIVE_SESSION_ID: active_session_id,
            constants.KEY_SIGNINS: signins,
        }

    # --- Officials --------------------------------------------------------------

    def list_officials(self, on_date: date) -> list[dict[str, Any]]:
        """Everyone known, for the name search (member IDs left out).

        Args:
            on_date: Date used to work out years certified.

        Returns:
            Officials sorted by name, each with ``id``, ``name``, ``club``, ``lsc``,
            ``zone``, ``years_certified``, ``trainee``, ``roles`` (last worked) and
            ``card_meet_id`` (meet where their card was last scanned, or None).
        """
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, name, lsc, club, certified_since_year, trainee, last_roles_json, card_meet_id "
                "FROM officials ORDER BY name COLLATE NOCASE LIMIT ?",
                (constants.OFFICIAL_SEARCH_LIMIT,),
            ).fetchall()
        return [self._official_summary(row, on_date) for row in rows]

    @staticmethod
    def _official_summary(row: sqlite3.Row, on_date: date) -> dict[str, Any]:
        """Page-safe view of an official row (no member ID)."""
        return {
            constants.KEY_ID: row["id"],
            constants.KEY_NAME: row["name"],
            constants.KEY_CLUB: row["club"],
            constants.KEY_LSC: row["lsc"],
            constants.KEY_ZONE: None if row["lsc"] is None else constants.ZONE_BY_LSC_CODE.get(row["lsc"]),
            constants.KEY_YEARS_CERTIFIED: since_year_to_years(row["certified_since_year"], on_date),
            constants.KEY_TRAINEE: bool(row["trainee"]),
            constants.KEY_ROLES: json.loads(row["last_roles_json"] or "[]"),
            constants.KEY_CARD_MEET_ID: row["card_meet_id"],
        }

    def get_official(self, official_id: int, on_date: date) -> dict[str, Any] | None:
        """Page-safe view of one official, or None."""
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM officials WHERE id = ?", (official_id,)).fetchone()
        return None if row is None else self._official_summary(row, on_date)

    def find_official_for_card(self, reading: CardReading) -> int | None:
        """Find a known official matching a card: by member ID, else by name.

        Args:
            reading: Card reading.

        Returns:
            The official's ID, or None if this is someone new.
        """
        with self._connect() as connection:
            if reading.member_id is not None:
                row = connection.execute(
                    "SELECT id FROM officials WHERE member_id = ? ORDER BY id LIMIT 1", (reading.member_id,)
                ).fetchone()
                if row is not None:
                    return int(row["id"])
            if reading.name is not None:
                row = connection.execute(
                    "SELECT id FROM officials WHERE name_key = ? ORDER BY id LIMIT 1", (name_key(reading.name),)
                ).fetchone()
                if row is not None:
                    return int(row["id"])
        return None

    def save_official(
        self,
        official_id: int | None,
        name: str | None,
        years_certified: int | None,
        reading: CardReading | None,
        meet_id: int | None,
        today: date,
    ) -> int:
        """Create or update an official from the sign-in form and any card reading.

        Values from the card (name, member ID, LSC, club) win over stored ones.
        Values left empty on the form keep what is stored.

        Args:
            official_id: Existing official, or None to create one.
            name: Name typed on the form, or None.
            years_certified: Years certified from the form, or None to keep.
            reading: Card reading from the camera, or None.
            meet_id: Meet the card was checked at (so later sessions reuse the check).
            today: Today's date (for years certified).

        Returns:
            The official's ID.

        Raises:
            SigninError: If a new official has no name, or the ID is unknown.
        """
        card_name = None if reading is None else reading.name
        chosen_name = (card_name or name or "").strip()[: constants.NAME_MAX_LENGTH]
        now = utc_now_iso()
        since_year = years_to_since_year(years_certified, today)
        card_json = None if reading is None else json.dumps(reading.to_dict())
        with self._connect() as connection:
            if official_id is None:
                if not chosen_name:
                    raise SigninError("A name is needed")
                cursor = connection.execute(
                    "INSERT INTO officials (name, name_key, member_id, lsc, club, certified_since_year, "
                    "card_json, card_meet_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        chosen_name, name_key(chosen_name),
                        None if reading is None else reading.member_id,
                        None if reading is None else reading.lsc,
                        None if reading is None else reading.club,
                        since_year, card_json, None if reading is None else meet_id, now, now,
                    ),
                )
                return int(cursor.lastrowid)
            row = connection.execute("SELECT * FROM officials WHERE id = ?", (official_id,)).fetchone()
            if row is None:
                raise SigninError("Unknown official")
            updated_name = chosen_name or row["name"]
            connection.execute(
                "UPDATE officials SET name = ?, name_key = ?, member_id = ?, lsc = ?, club = ?, "
                "certified_since_year = ?, card_json = ?, card_meet_id = ?, updated_at = ? WHERE id = ?",
                (
                    updated_name, name_key(updated_name),
                    (reading.member_id if reading is not None and reading.member_id else row["member_id"]),
                    (reading.lsc if reading is not None and reading.lsc else row["lsc"]),
                    (reading.club if reading is not None and reading.club else row["club"]),
                    since_year if since_year is not None else row["certified_since_year"],
                    card_json if card_json is not None else row["card_json"],
                    meet_id if reading is not None else row["card_meet_id"],
                    now, official_id,
                ),
            )
        return official_id

    def stored_card_validation(self, official_id: int, meet_id: int, session_date: date) -> Validation | None:
        """Reuse a card check made earlier at the same meet, if it still passes.

        An official scanned for the morning session is not scanned again for the
        afternoon. A check from an earlier meet is not reused.

        Returns:
            A camera validation, or None when there is no usable earlier check.
        """
        with self._connect() as connection:
            row = connection.execute(
                "SELECT card_json, card_meet_id FROM officials WHERE id = ?", (official_id,)
            ).fetchone()
        if row is None or row["card_json"] is None or row["card_meet_id"] != meet_id:
            return None
        stored = json.loads(row["card_json"])
        reading = CardReading(**{
            name: stored.get(name) for name in CardReading.__dataclass_fields__
        })
        result = check_card(reading, session_date)
        return Validation(result.validated, constants.VALIDATION_CAMERA, result.problems)

    # --- Sign-ins --------------------------------------------------------------

    def sign_in(
        self,
        official_id: int,
        session_ids: list[int],
        roles: list[str],
        trainee: bool,
        validation_by_session: dict[int, Validation],
    ) -> list[int]:
        """Sign an official in to one or more sessions (signing in again updates).

        Args:
            official_id: The official.
            session_ids: The active session plus any later sessions they pre-sign up for.
            roles: Roles they will work (from ``constants.ROSTER_ROLES``).
            trainee: True for a trainee (must be paired with a certified official).
            validation_by_session: Outcome of the check for each session.

        Returns:
            The sign-in IDs, one per session.

        Raises:
            SigninError: If a role is unknown or no role/session was given.
        """
        if not roles:
            raise SigninError("Pick at least one role")
        unknown = [role for role in roles if role not in constants.ROSTER_ROLES]
        if unknown:
            raise SigninError(f"Unknown role: {unknown[0]}")
        if not session_ids:
            raise SigninError("No session to sign in to")
        now = utc_now_iso()
        signin_ids = []
        with self._connect() as connection:
            for session_id in session_ids:
                validation = validation_by_session[session_id]
                connection.execute(
                    "INSERT INTO signins (session_id, official_id, roles_json, trainee, validated, "
                    "validation_method, problems_json, signed_in_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(session_id, official_id) DO UPDATE SET roles_json = excluded.roles_json, "
                    "trainee = excluded.trainee, "
                    # Never downgrade an earlier successful check by signing in again.
                    "validated = MAX(signins.validated, excluded.validated), "
                    "validation_method = CASE WHEN signins.validated = 1 AND excluded.validated = 0 "
                    "THEN signins.validation_method ELSE excluded.validation_method END, "
                    "problems_json = CASE WHEN signins.validated = 1 AND excluded.validated = 0 "
                    "THEN signins.problems_json ELSE excluded.problems_json END",
                    (
                        session_id, official_id, json.dumps(roles), int(trainee), int(validation.validated),
                        validation.method, json.dumps(validation.problems), now,
                    ),
                )
                row = connection.execute(
                    "SELECT id FROM signins WHERE session_id = ? AND official_id = ?", (session_id, official_id)
                ).fetchone()
                signin_ids.append(int(row["id"]))
            connection.execute(
                "UPDATE officials SET last_roles_json = ?, trainee = ?, updated_at = ? WHERE id = ?",
                (json.dumps(roles), int(trainee), now, official_id),
            )
        return signin_ids

    def list_signins(self, session_id: int) -> list[dict[str, Any]]:
        """Sign-ins for a session, newest first, joined with the official's details.

        Returns:
            Dictionaries with ``id``, ``official_id``, ``name``, ``club``, ``lsc``,
            ``zone``, ``years_certified``, ``roles``, ``trainee``, ``validated``,
            ``validation_method``, ``problems`` and ``team``.
        """
        session = self.get_session(session_id)
        on_date = date.today() if session is None else date.fromisoformat(session["date"])
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT g.id, g.official_id, g.roles_json, g.trainee, g.validated, g.validation_method, "
                "g.problems_json, g.team, o.name, o.lsc, o.club, o.certified_since_year "
                "FROM signins g JOIN officials o ON o.id = g.official_id "
                "WHERE g.session_id = ? ORDER BY g.signed_in_at DESC, g.id DESC",
                (session_id,),
            ).fetchall()
        return [
            {
                constants.KEY_ID: row["id"],
                constants.KEY_OFFICIAL_ID: row["official_id"],
                constants.KEY_NAME: row["name"],
                constants.KEY_CLUB: row["club"],
                constants.KEY_LSC: row["lsc"],
                constants.KEY_ZONE: None if row["lsc"] is None else constants.ZONE_BY_LSC_CODE.get(row["lsc"]),
                constants.KEY_YEARS_CERTIFIED: since_year_to_years(row["certified_since_year"], on_date),
                constants.KEY_ROLES: json.loads(row["roles_json"]),
                constants.KEY_TRAINEE: bool(row["trainee"]),
                constants.KEY_VALIDATED: bool(row["validated"]),
                constants.KEY_VALIDATION_METHOD: row["validation_method"],
                constants.KEY_PROBLEMS: json.loads(row["problems_json"] or "[]"),
                constants.KEY_TEAM: row["team"],
            }
            for row in rows
        ]

    def validate_signin_visually(self, signin_id: int) -> bool:
        """Mark a sign-in validated because the admin looked at the card.

        Returns:
            True if the sign-in exists.
        """
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE signins SET validated = 1, validation_method = ?, problems_json = ? WHERE id = ?",
                (constants.VALIDATION_VISUAL, json.dumps([]), signin_id),
            )
        return cursor.rowcount > 0

    def remove_signin(self, signin_id: int) -> bool:
        """Remove a sign-in (signed in by mistake). The official stays known.

        Returns:
            True if the sign-in existed.
        """
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM signins WHERE id = ?", (signin_id,))
        return cursor.rowcount > 0

    def roster_source(self, session_id: int) -> dict[str, Any] | None:
        """The meet, session and sign-ins needed to build the roster file.

        Returns:
            ``{"meet": {...}, "session": {...}, "signins": [...]}``, or None if the
            session does not exist. Sign-ins include ``member_id`` for the file.
        """
        with self._connect() as connection:
            session = connection.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if session is None:
                return None
            meet = connection.execute(
                "SELECT name, start_date FROM meets WHERE id = ?", (session["meet_id"],)
            ).fetchone()
            member_ids = {
                row["id"]: row["member_id"]
                for row in connection.execute(
                    "SELECT o.id, o.member_id FROM officials o JOIN signins g ON g.official_id = o.id "
                    "WHERE g.session_id = ?",
                    (session_id,),
                )
            }
        signins = self.list_signins(session_id)
        for signin in signins:
            signin[constants.KEY_MEMBER_ID] = member_ids.get(signin[constants.KEY_OFFICIAL_ID])
        return {
            constants.KEY_MEET: dict(meet),
            constants.ROSTER_KEY_SESSION: dict(session),
            constants.KEY_SIGNINS: signins,
        }


def not_checked_validation() -> Validation:
    """Validation for an official whose card has not been checked (goes to the admin)."""
    return Validation(False, constants.VALIDATION_NONE, [_NOT_CHECKED_PROBLEM])
