"""SQLite storage for dq_transcribe.

Holds every clip (the queue and its measurements) and the editable utterances
transcribed from it. Uses only the standard library. Each call opens its own
short-lived connection, so one ``Database`` object is safe to share between the
web server threads and the transcription worker.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from dq_transcribe import constants
from dq_transcribe.audio_analysis import ClipAnalysis
from dq_transcribe.grouping import assign_conversation_groups, parse_timestamp

_CREATE_CLIPS_TABLE = """
CREATE TABLE IF NOT EXISTS clips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    ended_at TEXT,
    audio_filename TEXT NOT NULL,
    status TEXT NOT NULL,
    error_message TEXT,
    capture_info_json TEXT,
    duration_seconds REAL,
    peak_dbfs REAL,
    rms_dbfs REAL,
    levels_json TEXT,
    pauses_json TEXT,
    analysis_params_json TEXT,
    whisper_model TEXT,
    transcribe_seconds REAL,
    processed_at TEXT,
    trashed_at TEXT,
    refine_status TEXT,
    refine_model TEXT,
    refine_seconds REAL,
    refined_at TEXT
)
"""

# `speaker` is reserved for future speaker labelling and is unused for now.
_CREATE_UTTERANCES_TABLE = """
CREATE TABLE IF NOT EXISTS utterances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clip_id INTEGER NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    start_seconds REAL NOT NULL,
    end_seconds REAL NOT NULL,
    speaker TEXT,
    text TEXT NOT NULL,
    original_text TEXT NOT NULL,
    edited_at TEXT,
    raw_output TEXT,
    refined_text TEXT,
    refined_raw_output TEXT
)
"""

_CREATE_MEETS_TABLE = """
CREATE TABLE IF NOT EXISTS meets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    start_date TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""

_CREATE_MEET_OFFICIALS_TABLE = """
CREATE TABLE IF NOT EXISTS meet_officials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meet_id INTEGER NOT NULL REFERENCES meets(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    name TEXT NOT NULL,
    role TEXT NOT NULL
)
"""

# Small key/value store for app-wide settings, such as the active meet.
_CREATE_SETTINGS_TABLE = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
)
"""

_CREATE_UTTERANCES_INDEX = "CREATE INDEX IF NOT EXISTS utterances_clip ON utterances(clip_id, position)"

# Columns added after the first release; `initialize` adds them to older databases.
_ADDED_CLIP_COLUMNS = {
    "started_at": "TEXT",
    "ended_at": "TEXT",
    "trashed_at": "TEXT",
    "refine_status": "TEXT",
    "refine_model": "TEXT",
    "refine_seconds": "REAL",
    "refined_at": "TEXT",
    "meet_id": "INTEGER",
}
_ADDED_UTTERANCE_COLUMNS = {"refined_text": "TEXT", "refined_raw_output": "TEXT"}

_CLIP_SUMMARY_COLUMNS = (
    "id, created_at, started_at, ended_at, audio_filename, status, error_message, duration_seconds, "
    "peak_dbfs, rms_dbfs, whisper_model, transcribe_seconds, processed_at, trashed_at, "
    "refine_status, refine_model, refine_seconds, refined_at, meet_id"
)
_CLIP_JSON_COLUMNS = ("capture_info_json", "levels_json", "pauses_json", "analysis_params_json")
_UTTERANCE_SUMMARY_COLUMNS = (
    "id, clip_id, position, start_seconds, end_seconds, speaker, text, original_text, edited_at, refined_text"
)
_UTTERANCE_FULL_COLUMNS = _UTTERANCE_SUMMARY_COLUMNS + ", raw_output, refined_raw_output"


@dataclass(frozen=True)
class NewUtterance:
    """One transcribed turn, ready to be stored.

    Attributes:
        position: Order of the turn within its clip, starting at 0.
        start_seconds: Turn start within the clip.
        end_seconds: Turn end within the clip.
        text: Transcript text.
        raw_output: The speech engine's raw output, kept for tuning.
    """

    position: int
    start_seconds: float
    end_seconds: float
    text: str
    raw_output: str


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_json_column(value: str | None) -> Any:
    """Decode a JSON text column, returning None if empty or invalid."""
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


class Database:
    """The app's SQLite database."""

    def __init__(self, path: Path) -> None:
        """Remember where the database file lives.

        Args:
            path: Database file; its folder is created by ``initialize``.
        """
        self._path = path

    def connection(self) -> AbstractContextManager[sqlite3.Connection]:
        """Public form of ``_connection`` for other stores sharing this database file."""
        return self._connection()

    def transaction(self) -> AbstractContextManager[sqlite3.Connection]:
        """Public form of ``_transaction`` for other stores sharing this database file."""
        return self._transaction()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """Open a short-lived connection in autocommit mode."""
        connection = sqlite3.connect(
            self._path, timeout=constants.DATABASE_TIMEOUT_SECONDS, isolation_level=None
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        """Open a connection and run the body as one write transaction."""
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                connection.execute("ROLLBACK")
                raise
            else:
                connection.execute("COMMIT")

    def initialize(self) -> None:
        """Create the database file and tables if they do not exist."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(_CREATE_CLIPS_TABLE)
            connection.execute(_CREATE_UTTERANCES_TABLE)
            connection.execute(_CREATE_UTTERANCES_INDEX)
            connection.execute(_CREATE_MEETS_TABLE)
            connection.execute(_CREATE_SETTINGS_TABLE)
            connection.execute(_CREATE_MEET_OFFICIALS_TABLE)
            existing_columns = {row["name"] for row in connection.execute("PRAGMA table_info(clips)")}
            for column, column_type in _ADDED_CLIP_COLUMNS.items():
                if column not in existing_columns:
                    connection.execute(f"ALTER TABLE clips ADD COLUMN {column} {column_type}")
            existing_columns = {row["name"] for row in connection.execute("PRAGMA table_info(meets)")}
            if "closed_at" not in existing_columns:
                connection.execute("ALTER TABLE meets ADD COLUMN closed_at TEXT")
            existing_columns = {row["name"] for row in connection.execute("PRAGMA table_info(utterances)")}
            for column, column_type in _ADDED_UTTERANCE_COLUMNS.items():
                if column not in existing_columns:
                    connection.execute(f"ALTER TABLE utterances ADD COLUMN {column} {column_type}")

    def add_clip(
        self,
        audio_filename: str,
        capture_info_json: str | None,
        started_at: str | None = None,
        ended_at: str | None = None,
        meet_id: int | None = None,
    ) -> int:
        """Queue a newly uploaded clip for transcription.

        Args:
            audio_filename: Name of the WAV file in the recordings directory.
            capture_info_json: What the browser reported about the capture, as JSON text.
            started_at: When the clip's audio began (UTC ISO text), if the browser reported it.
            ended_at: When the clip's audio ended (UTC ISO text), if the browser reported it.
            meet_id: Meet the clip belongs to (normally the active meet), or None.

        Returns:
            The new clip's id.
        """
        with self._transaction() as connection:
            cursor = connection.execute(
                "INSERT INTO clips (created_at, started_at, ended_at, audio_filename, status, capture_info_json, meet_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (utc_now_iso(), started_at, ended_at, audio_filename, constants.CLIP_STATUS_QUEUED, capture_info_json, meet_id),
            )
            return int(cursor.lastrowid)

    def claim_next_queued_clip(self) -> dict[str, Any] | None:
        """Take the oldest queued clip and mark it as processing.

        Returns:
            ``{"id", "audio_filename"}`` for the claimed clip, or None if the queue is empty.
        """
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT id, audio_filename FROM clips WHERE status = ? AND trashed_at IS NULL ORDER BY id LIMIT 1",
                (constants.CLIP_STATUS_QUEUED,),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                "UPDATE clips SET status = ?, error_message = NULL WHERE id = ?",
                (constants.CLIP_STATUS_PROCESSING, row["id"]),
            )
            return dict(row)

    def requeue_interrupted_clips(self) -> int:
        """Return clips left in "processing" (for example after a crash) to their queues.

        Covers both the draft pass and the refine pass.

        Returns:
            How many clips were requeued.
        """
        with self._transaction() as connection:
            cursor = connection.execute(
                "UPDATE clips SET status = ? WHERE status = ?",
                (constants.CLIP_STATUS_QUEUED, constants.CLIP_STATUS_PROCESSING),
            )
            connection.execute(
                "UPDATE clips SET refine_status = ? WHERE refine_status = ?",
                (constants.CLIP_STATUS_QUEUED, constants.CLIP_STATUS_PROCESSING),
            )
            return cursor.rowcount

    def save_processing_result(
        self,
        clip_id: int,
        analysis: ClipAnalysis,
        utterances: list[NewUtterance],
        whisper_model: str,
        transcribe_seconds: float,
        queue_refine: bool = False,
    ) -> None:
        """Store a finished clip's measurements and utterances, replacing earlier ones.

        Args:
            clip_id: Clip that was processed.
            analysis: Loudness, pauses, and turns measured for the clip.
            utterances: Transcribed turns.
            whisper_model: Name of the model that produced the text.
            transcribe_seconds: Total processing time for the clip.
            queue_refine: Queue the clip for the second, more accurate pass.
        """
        if not queue_refine:
            refine_status = None
        elif utterances:
            refine_status = constants.CLIP_STATUS_QUEUED
        else:
            refine_status = constants.REFINE_STATUS_SKIPPED
        with self._transaction() as connection:
            timing = connection.execute(
                "SELECT created_at, started_at, ended_at FROM clips WHERE id = ?", (clip_id,)
            ).fetchone()
            # Browser-reported times win; otherwise assume the clip ended at upload.
            ended_at = timing["ended_at"] or timing["created_at"]
            started_at = timing["started_at"] or (
                parse_timestamp(ended_at) - timedelta(seconds=analysis.duration_seconds)
            ).astimezone(timezone.utc).isoformat(timespec="milliseconds")

            connection.execute("DELETE FROM utterances WHERE clip_id = ?", (clip_id,))
            connection.executemany(
                "INSERT INTO utterances (clip_id, position, start_seconds, end_seconds, text, original_text, raw_output) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (clip_id, u.position, u.start_seconds, u.end_seconds, u.text, u.text, u.raw_output)
                    for u in utterances
                ],
            )
            connection.execute(
                "UPDATE clips SET started_at = ?, ended_at = ?, status = ?, error_message = NULL, "
                "duration_seconds = ?, peak_dbfs = ?, rms_dbfs = ?, levels_json = ?, pauses_json = ?, "
                "analysis_params_json = ?, whisper_model = ?, transcribe_seconds = ?, processed_at = ?, "
                "refine_status = ?, refine_model = NULL, refine_seconds = NULL, refined_at = NULL WHERE id = ?",
                (
                    started_at,
                    ended_at,
                    constants.CLIP_STATUS_DONE,
                    analysis.duration_seconds,
                    analysis.peak_dbfs,
                    analysis.rms_dbfs,
                    json.dumps(analysis.frame_levels_dbfs),
                    json.dumps([[p.start_seconds, p.end_seconds] for p in analysis.pauses]),
                    json.dumps(analysis.parameters),
                    whisper_model,
                    transcribe_seconds,
                    utc_now_iso(),
                    refine_status,
                    clip_id,
                ),
            )

    def claim_next_refine_clip(self) -> dict[str, Any] | None:
        """Take the oldest clip waiting for the refine pass and mark it as refining.

        Returns:
            ``{"id", "audio_filename", "utterances": [{"id", "start_seconds", "end_seconds"}]}``,
            or None if nothing is waiting.
        """
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT id, audio_filename FROM clips WHERE status = ? AND refine_status = ? "
                "AND trashed_at IS NULL ORDER BY id LIMIT 1",
                (constants.CLIP_STATUS_DONE, constants.CLIP_STATUS_QUEUED),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                "UPDATE clips SET refine_status = ? WHERE id = ?", (constants.CLIP_STATUS_PROCESSING, row["id"])
            )
            turns = connection.execute(
                "SELECT id, start_seconds, end_seconds FROM utterances WHERE clip_id = ? ORDER BY position",
                (row["id"],),
            )
            return {**dict(row), "utterances": [dict(turn) for turn in turns]}

    def save_refine_result(
        self, clip_id: int, refined: list[tuple[int, str, str]], model: str, refine_seconds: float
    ) -> bool:
        """Store the refine pass. Lines edited by hand keep their edit.

        Args:
            clip_id: Clip that was refined.
            refined: ``(utterance_id, text, raw_output)`` for each turn.
            model: Name of the refine model.
            refine_seconds: Time the refine pass took.

        Returns:
            False if the clip was reprocessed or deleted meanwhile (nothing is saved).
        """
        with self._transaction() as connection:
            row = connection.execute("SELECT refine_status FROM clips WHERE id = ?", (clip_id,)).fetchone()
            if row is None or row["refine_status"] != constants.CLIP_STATUS_PROCESSING:
                return False
            connection.executemany(
                "UPDATE utterances SET refined_text = ?, refined_raw_output = ?, "
                "text = CASE WHEN edited_at IS NULL THEN ? ELSE text END WHERE id = ? AND clip_id = ?",
                [(text, raw, text, utterance_id, clip_id) for utterance_id, text, raw in refined],
            )
            connection.execute(
                "UPDATE clips SET refine_status = ?, refine_model = ?, refine_seconds = ?, refined_at = ? WHERE id = ?",
                (constants.CLIP_STATUS_DONE, model, refine_seconds, utc_now_iso(), clip_id),
            )
            return True

    def mark_refine_failed(self, clip_id: int) -> None:
        """Record that the refine pass failed; the draft text stays.

        Args:
            clip_id: Clip whose refine pass failed.
        """
        with self._transaction() as connection:
            connection.execute(
                "UPDATE clips SET refine_status = ? WHERE id = ? AND refine_status = ?",
                (constants.CLIP_STATUS_FAILED, clip_id, constants.CLIP_STATUS_PROCESSING),
            )

    def mark_clip_failed(self, clip_id: int, message: str) -> None:
        """Record that processing a clip failed.

        Args:
            clip_id: Clip that failed.
            message: Short description of what went wrong.
        """
        with self._transaction() as connection:
            connection.execute(
                "UPDATE clips SET status = ?, error_message = ?, processed_at = ? WHERE id = ?",
                (constants.CLIP_STATUS_FAILED, message, utc_now_iso(), clip_id),
            )

    def requeue_clip(self, clip_id: int) -> bool:
        """Send a finished or failed clip back through transcription.

        Existing utterances (including edits) are deleted.

        Args:
            clip_id: Clip to reprocess.

        Returns:
            True if the clip was requeued; False if it does not exist or is still waiting or running.
        """
        with self._transaction() as connection:
            row = connection.execute("SELECT status FROM clips WHERE id = ?", (clip_id,)).fetchone()
            if row is None or row["status"] not in (constants.CLIP_STATUS_DONE, constants.CLIP_STATUS_FAILED):
                return False
            connection.execute("DELETE FROM utterances WHERE clip_id = ?", (clip_id,))
            connection.execute(
                "UPDATE clips SET status = ?, error_message = NULL, refine_status = NULL WHERE id = ?",
                (constants.CLIP_STATUS_QUEUED, clip_id),
            )
            return True

    def trash_clip(self, clip_id: int) -> bool:
        """Move a clip to the trash bin. Its audio and transcript are kept.

        A trashed clip is hidden from the clip list and transcript, and is not
        transcribed if it was still waiting in the queue.

        Args:
            clip_id: Clip to trash.

        Returns:
            True if the clip existed and was not already in the trash.
        """
        with self._transaction() as connection:
            cursor = connection.execute(
                "UPDATE clips SET trashed_at = ? WHERE id = ? AND trashed_at IS NULL", (utc_now_iso(), clip_id)
            )
            return cursor.rowcount > 0

    def restore_clip(self, clip_id: int) -> bool:
        """Take a clip back out of the trash bin.

        Args:
            clip_id: Clip to restore.

        Returns:
            True if the clip was in the trash.
        """
        with self._transaction() as connection:
            cursor = connection.execute(
                "UPDATE clips SET trashed_at = NULL WHERE id = ? AND trashed_at IS NOT NULL", (clip_id,)
            )
            return cursor.rowcount > 0

    def delete_trashed_clip(self, clip_id: int) -> str | None:
        """Permanently delete a clip that is in the trash, with its utterances.

        The caller deletes the audio file.

        Args:
            clip_id: Clip to delete.

        Returns:
            The deleted clip's audio file name, or None if it does not exist or is not in the trash.
        """
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT audio_filename FROM clips WHERE id = ? AND trashed_at IS NOT NULL", (clip_id,)
            ).fetchone()
            if row is None:
                return None
            connection.execute("DELETE FROM utterances WHERE clip_id = ?", (clip_id,))
            connection.execute("DELETE FROM clips WHERE id = ?", (clip_id,))
            return str(row["audio_filename"])

    def update_utterance_text(self, utterance_id: int, text: str) -> bool:
        """Save an edit to an utterance's text. The original text is kept.

        Args:
            utterance_id: Utterance to edit.
            text: New text.

        Returns:
            True if the utterance exists.
        """
        with self._transaction() as connection:
            cursor = connection.execute(
                "UPDATE utterances SET text = ?, edited_at = ? WHERE id = ?",
                (text, utc_now_iso(), utterance_id),
            )
            return cursor.rowcount > 0

    def get_clip_audio_filename(self, clip_id: int) -> str | None:
        """Look up the audio file name of a clip.

        Args:
            clip_id: Clip to look up.

        Returns:
            The file name, or None if there is no such clip.
        """
        with self._connection() as connection:
            row = connection.execute("SELECT audio_filename FROM clips WHERE id = ?", (clip_id,)).fetchone()
        return None if row is None else str(row["audio_filename"])

    # --- Meets -------------------------------------------------------------

    def create_meet(self, name: str, start_date: str) -> int:
        """Add a meet and make it the active meet.

        Args:
            name: Meet name, for example "Candy Meet".
            start_date: First day, ``YYYY-MM-DD``.

        Returns:
            The new meet's id.
        """
        with self._transaction() as connection:
            cursor = connection.execute(
                "INSERT INTO meets (name, start_date, created_at) VALUES (?, ?, ?)", (name, start_date, utc_now_iso())
            )
            meet_id = int(cursor.lastrowid)
            self._set_setting(connection, constants.SETTING_ACTIVE_MEET_ID, str(meet_id))
            return meet_id

    def list_meets(self) -> list[dict[str, Any]]:
        """All meets, newest first (by start date, then name), with their clip counts."""
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT m.id, m.name, m.start_date, m.created_at, m.closed_at, "
                "(SELECT COUNT(*) FROM clips c WHERE c.meet_id = m.id AND c.trashed_at IS NULL) AS clip_count "
                "FROM meets m ORDER BY m.start_date DESC, m.name"
            )
            meets = [dict(row) for row in rows]
            for meet in meets:
                meet["officials"] = [
                    dict(row)
                    for row in connection.execute(
                        "SELECT name, role FROM meet_officials WHERE meet_id = ? ORDER BY position", (meet["id"],)
                    )
                ]
            return meets

    def update_meet(self, meet_id: int, name: str, start_date: str, officials: list[tuple[str, str]]) -> bool:
        """Change a meet's name, first day and officials roster.

        Args:
            meet_id: Meet to change.
            name: New name.
            start_date: New first day, ``YYYY-MM-DD``.
            officials: ``(name, role)`` pairs, in display order; replaces the roster.

        Returns:
            False if there is no such meet. Audio files already recorded keep their folder.
        """
        with self._transaction() as connection:
            cursor = connection.execute("UPDATE meets SET name = ?, start_date = ? WHERE id = ?", (name, start_date, meet_id))
            if cursor.rowcount == 0:
                return False
            connection.execute("DELETE FROM meet_officials WHERE meet_id = ?", (meet_id,))
            connection.executemany(
                "INSERT INTO meet_officials (meet_id, position, name, role) VALUES (?, ?, ?, ?)",
                [(meet_id, position, official_name, role) for position, (official_name, role) in enumerate(officials)],
            )
            return True

    def get_meet(self, meet_id: int) -> dict[str, Any] | None:
        """One meet, or None if there is no such meet."""
        with self._connection() as connection:
            row = connection.execute("SELECT id, name, start_date, closed_at FROM meets WHERE id = ?", (meet_id,)).fetchone()
        return None if row is None else dict(row)

    def set_meet_closed(self, meet_id: int, closed: bool) -> bool:
        """Close a meet (unlocks permanent deletes from its trash) or reopen it.

        Returns:
            False if there is no such meet.
        """
        with self._transaction() as connection:
            cursor = connection.execute(
                "UPDATE meets SET closed_at = ? WHERE id = ?", (utc_now_iso() if closed else None, meet_id)
            )
            return cursor.rowcount > 0

    def clip_meet_is_open(self, clip_id: int) -> bool:
        """True if the clip belongs to a meet that is not closed (its permanent delete must wait)."""
        with self._connection() as connection:
            row = connection.execute(
                "SELECT m.closed_at FROM clips c JOIN meets m ON m.id = c.meet_id WHERE c.id = ?", (clip_id,)
            ).fetchone()
        return row is not None and row["closed_at"] is None

    def get_active_meet_id(self) -> int | None:
        """The active meet's id (new clips are filed under it), or None."""
        with self._connection() as connection:
            row = connection.execute(
                "SELECT value FROM settings WHERE key = ?", (constants.SETTING_ACTIVE_MEET_ID,)
            ).fetchone()
        if row is None or not row["value"]:
            return None
        return int(row["value"])

    def set_active_meet(self, meet_id: int | None) -> bool:
        """Make a meet active, or clear the active meet with None.

        Returns:
            False if the meet does not exist.
        """
        with self._transaction() as connection:
            if meet_id is not None:
                if connection.execute("SELECT 1 FROM meets WHERE id = ?", (meet_id,)).fetchone() is None:
                    return False
            self._set_setting(connection, constants.SETTING_ACTIVE_MEET_ID, "" if meet_id is None else str(meet_id))
            return True

    def assign_clips_to_meet(self, meet_id: int | None, clip_ids: list[int]) -> int:
        """File existing clips under a meet (or under no meet with None). Audio files are not moved.

        Returns:
            How many clips were updated.
        """
        with self._transaction() as connection:
            if meet_id is not None and connection.execute("SELECT 1 FROM meets WHERE id = ?", (meet_id,)).fetchone() is None:
                return 0
            cursor = connection.executemany("UPDATE clips SET meet_id = ? WHERE id = ?", [(meet_id, clip_id) for clip_id in clip_ids])
            return cursor.rowcount

    def get_setting(self, key: str, default: str = "") -> str:
        """An app setting (``default`` if it was never stored)."""
        with self._connection() as connection:
            row = connection.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return default if row is None else row["value"]

    def set_setting(self, key: str, value: str) -> None:
        """Store an app setting."""
        with self._transaction() as connection:
            self._set_setting(connection, key, value)

    @staticmethod
    def _set_setting(connection: sqlite3.Connection, key: str, value: str) -> None:
        """Store an app setting (inside the caller's transaction)."""
        connection.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    # --- Clip lists ----------------------------------------------------------

    def list_clips(
        self,
        limit: int | None = None,
        newest_first: bool = True,
        trashed: bool = False,
        meet_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """List clips with their utterances (without the bulky measurement data).

        Args:
            limit: Maximum number of clips, or None for all.
            newest_first: Sort newest first (True) or oldest first (False).
            trashed: List the clips in the trash bin instead of the active ones.
            meet_id: Only clips of this meet (None = all clips).

        Returns:
            Clip dictionaries, each with an ``utterances`` list and a ``group_id``
            (clips that follow each other closely share a group).
        """
        order = "DESC" if newest_first else "ASC"
        trash_filter = "trashed_at IS NOT NULL" if trashed else "trashed_at IS NULL"
        parameters: tuple[Any, ...] = ()
        if meet_id is not None:
            trash_filter += " AND meet_id = ?"
            parameters = (meet_id,)
        query = f"SELECT {_CLIP_SUMMARY_COLUMNS} FROM clips WHERE {trash_filter} ORDER BY id {order}"
        if limit is not None:
            query += " LIMIT ?"
            parameters = (*parameters, limit)
        with self._connection() as connection:
            clips = [dict(row) for row in connection.execute(query, parameters)]
            self._attach_utterances(connection, clips, _UTTERANCE_SUMMARY_COLUMNS)
        assign_conversation_groups(clips)
        return clips

    def export_all(self) -> dict[str, Any]:
        """Return everything stored, including measurements and raw engine output.

        Returns:
            A JSON-serializable dictionary, oldest clip first.
        """
        with self._connection() as connection:
            clips = [dict(row) for row in connection.execute("SELECT * FROM clips ORDER BY id")]
            for clip in clips:
                for column in _CLIP_JSON_COLUMNS:
                    clip[column.removesuffix("_json")] = _parse_json_column(clip.pop(column))
            self._attach_utterances(connection, clips, _UTTERANCE_FULL_COLUMNS)
            meets = [dict(row) for row in connection.execute("SELECT * FROM meets ORDER BY id")]
        assign_conversation_groups(clips)
        return {"exported_at": utc_now_iso(), constants.RESPONSE_KEY_MEETS: meets, constants.RESPONSE_KEY_CLIPS: clips}

    @staticmethod
    def _attach_utterances(connection: sqlite3.Connection, clips: list[dict[str, Any]], columns: str) -> None:
        """Add an ``utterances`` list (ordered by position) to each clip dictionary."""
        by_clip: dict[int, list[dict[str, Any]]] = {clip["id"]: [] for clip in clips}
        if by_clip:
            placeholders = ", ".join("?" for _ in by_clip)
            rows = connection.execute(
                f"SELECT {columns} FROM utterances WHERE clip_id IN ({placeholders}) ORDER BY clip_id, position",
                tuple(by_clip),
            )
            for row in rows:
                by_clip[row["clip_id"]].append(dict(row))
        for clip in clips:
            clip["utterances"] = by_clip[clip["id"]]
