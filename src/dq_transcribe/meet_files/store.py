"""Meet programs in the app database: loaded files, events, entries and sessions.

Each loaded Meet Manager file is kept as a dated version; nothing loaded earlier
is overwritten, and the newest file of a meet is the active one. Lookups (who
swam event 12, heat 2, lane 4?) and event details always use the active file.

Tables (sharing the app's SQLite database):

* ``meet_files``: one row per loaded file (meet, time, where it came from, format, summary).
* ``meet_program_events``, ``meet_program_entries``, ``meet_program_sessions``:
  the file's contents.
"""

from __future__ import annotations

import json
from typing import Any

from dq_transcribe.database import Database, utc_now_iso
from dq_transcribe.meet_files.model import MeetProgram, normalize_event_number, stroke_for_slip_codes

_CREATE_TABLES = (
    """
    CREATE TABLE IF NOT EXISTS meet_files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        meet_id INTEGER NOT NULL,
        loaded_at TEXT NOT NULL,
        source TEXT NOT NULL,
        original_name TEXT,
        file_format TEXT NOT NULL,
        stored_path TEXT,
        meet_name TEXT,
        summary TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS meet_program_events (
        file_id INTEGER NOT NULL REFERENCES meet_files(id) ON DELETE CASCADE,
        number TEXT NOT NULL,
        description TEXT,
        gender TEXT,
        age_group TEXT,
        distance INTEGER,
        course TEXT,
        stroke TEXT,
        relay INTEGER NOT NULL DEFAULT 0,
        session TEXT,
        round TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS meet_program_entries (
        file_id INTEGER NOT NULL REFERENCES meet_files(id) ON DELETE CASCADE,
        event_number TEXT NOT NULL,
        heat TEXT,
        lane TEXT,
        swimmer TEXT NOT NULL,
        club TEXT,
        age INTEGER,
        seed_time TEXT,
        relay INTEGER NOT NULL DEFAULT 0,
        relay_swimmers TEXT,
        round TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS meet_program_entries_lookup ON meet_program_entries (file_id, event_number, heat, lane)",
    """
    CREATE TABLE IF NOT EXISTS meet_program_sessions (
        file_id INTEGER NOT NULL REFERENCES meet_files(id) ON DELETE CASCADE,
        number TEXT NOT NULL,
        name TEXT,
        day TEXT,
        start_time TEXT,
        event_numbers TEXT
    )
    """,
)


class MeetProgramStore:
    """Loaded Meet Manager files and the lookups built on them."""

    def __init__(self, database: Database) -> None:
        """Use the app's database (call ``initialize`` once at start-up)."""
        self._database = database

    def initialize(self) -> None:
        """Create the tables if they do not exist."""
        with self._database.connection() as connection:
            for statement in _CREATE_TABLES:
                connection.execute(statement)

    def save(
        self,
        meet_id: int,
        program: MeetProgram,
        file_format: str,
        source: str,
        original_name: str = "",
        stored_path: str = "",
    ) -> int:
        """Store a newly read file as the meet's active version.

        Args:
            meet_id: The meet it belongs to.
            program: What was read from the file.
            file_format: One of the ``MEET_FILE_FORMAT_*`` constants.
            source: Where it came from (the file name picked, or the web address).
            original_name: The file's name.
            stored_path: Where the copy of the file is kept on this device.

        Returns:
            The new file id.
        """
        with self._database.transaction() as connection:
            cursor = connection.execute(
                "INSERT INTO meet_files (meet_id, loaded_at, source, original_name, file_format, stored_path, meet_name, summary) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (meet_id, utc_now_iso(), source, original_name, file_format, stored_path, program.meet_name,
                 json.dumps(program.summary())),
            )
            file_id = cursor.lastrowid
            connection.executemany(
                "INSERT INTO meet_program_events (file_id, number, description, gender, age_group, distance, course, stroke, relay, session, round) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(file_id, event.number, event.description, event.gender, event.age_group, event.distance, event.course,
                  event.stroke, int(event.relay), event.session, event.round) for event in program.events],
            )
            connection.executemany(
                "INSERT INTO meet_program_entries (file_id, event_number, heat, lane, swimmer, club, age, seed_time, relay, relay_swimmers, round) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(file_id, entry.event_number, entry.heat, entry.lane, entry.swimmer, entry.club, entry.age, entry.seed_time,
                  int(entry.relay), json.dumps(entry.relay_swimmers), entry.round) for entry in program.entries],
            )
            connection.executemany(
                "INSERT INTO meet_program_sessions (file_id, number, name, day, start_time, event_numbers) VALUES (?, ?, ?, ?, ?, ?)",
                [(file_id, session.number, session.name, session.day, session.start_time, json.dumps(session.event_numbers))
                 for session in program.sessions],
            )
            return int(file_id)

    def _active_file_id(self, connection: Any, meet_id: int | None) -> int | None:
        """The newest file of a meet."""
        if meet_id is None:
            return None
        row = connection.execute("SELECT id FROM meet_files WHERE meet_id = ? ORDER BY id DESC LIMIT 1", (meet_id,)).fetchone()
        return int(row["id"]) if row else None

    def files(self, meet_id: int) -> list[dict[str, Any]]:
        """Every file loaded for a meet, newest (active) first."""
        with self._database.connection() as connection:
            rows = connection.execute(
                "SELECT id, loaded_at, source, original_name, file_format, meet_name, summary FROM meet_files "
                "WHERE meet_id = ? ORDER BY id DESC",
                (meet_id,),
            )
            return [{**dict(row), "summary": json.loads(row["summary"])} for row in rows]

    def events(self, meet_id: int | None) -> dict[str, dict[str, Any]]:
        """The active file's events by number ("12" -> {description, stroke, ...})."""
        with self._database.connection() as connection:
            file_id = self._active_file_id(connection, meet_id)
            if file_id is None:
                return {}
            rows = connection.execute("SELECT * FROM meet_program_events WHERE file_id = ?", (file_id,))
            return {row["number"]: {**dict(row), "relay": bool(row["relay"])} for row in rows}

    def sessions(self, meet_id: int | None) -> list[dict[str, Any]]:
        """The active file's sessions, with their event numbers."""
        with self._database.connection() as connection:
            file_id = self._active_file_id(connection, meet_id)
            if file_id is None:
                return []
            rows = connection.execute("SELECT number, name, day, start_time, event_numbers FROM meet_program_sessions WHERE file_id = ?", (file_id,))
            return [{**dict(row), "event_numbers": json.loads(row["event_numbers"] or "[]")} for row in rows]

    def event_strokes(self, meet_id: int | None) -> dict[str, str]:
        """Each event's stroke for choosing slip codes (events where it is one stroke only)."""
        strokes = {}
        for number, event in self.events(meet_id).items():
            stroke = stroke_for_slip_codes(event["stroke"])
            if stroke:
                strokes[number] = stroke
        return strokes

    def lookup(self, meet_id: int | None, event: str | None, heat: str | None, lane: str | None) -> dict[str, Any] | None:
        """Who was seeded in an event, heat and lane (from the active file), or None.

        If the file has several rounds for the same heat and lane, the first one is
        used and ``ambiguous`` is set.
        """
        if not (event and heat and lane):
            return None
        with self._database.connection() as connection:
            file_id = self._active_file_id(connection, meet_id)
            if file_id is None:
                return None
            rows = connection.execute(
                "SELECT swimmer, club, age, seed_time, relay, relay_swimmers, round FROM meet_program_entries "
                "WHERE file_id = ? AND event_number = ? AND heat = ? AND lane = ?",
                (file_id, normalize_event_number(event), _number_text(heat), _number_text(lane)),
            ).fetchall()
        if not rows:
            return None
        first = rows[0]
        return {
            **dict(first),
            "relay": bool(first["relay"]),
            "relay_swimmers": json.loads(first["relay_swimmers"] or "[]"),
            "ambiguous": len(rows) > 1,
        }

    def summary(self, meet_id: int) -> dict[str, Any]:
        """The active file, older versions, events and sessions, for the Meet setup page."""
        files = self.files(meet_id)
        events = sorted(self.events(meet_id).values(), key=lambda event: _event_order(event["number"]))
        return {"active": files[0] if files else None, "history": files[1:], "events": events, "sessions": self.sessions(meet_id)}


def _number_text(value: str) -> str:
    """"02" -> "2" (heats and lanes are stored without leading zeros)."""
    text = str(value).strip()
    return str(int(text)) if text.isdigit() else text


def _event_order(number: str) -> tuple[int, str]:
    """Sort "2", "2b", "10" in meet order."""
    digits = "".join(character for character in number if character.isdigit())
    return (int(digits) if digits else 0, number)
