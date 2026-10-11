"""SQLite storage for dq_transcribe.

Holds every clip (the queue and its measurements) and the editable utterances
transcribed from it. Uses only the standard library. Each call opens its own
short-lived connection, so one ``Database`` object is safe to share between the
web server threads and the transcription worker.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
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
    processed_at TEXT
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
    raw_output TEXT
)
"""

_CREATE_UTTERANCES_INDEX = "CREATE INDEX IF NOT EXISTS utterances_clip ON utterances(clip_id, position)"

# Columns added after the first release; `initialize` adds them to older databases.
_ADDED_CLIP_COLUMNS = {"started_at": "TEXT", "ended_at": "TEXT"}

_CLIP_SUMMARY_COLUMNS = (
    "id, created_at, started_at, ended_at, audio_filename, status, error_message, duration_seconds, "
    "peak_dbfs, rms_dbfs, whisper_model, transcribe_seconds, processed_at"
)
_CLIP_JSON_COLUMNS = ("capture_info_json", "levels_json", "pauses_json", "analysis_params_json")
_UTTERANCE_SUMMARY_COLUMNS = "id, clip_id, position, start_seconds, end_seconds, speaker, text, original_text, edited_at"
_UTTERANCE_FULL_COLUMNS = _UTTERANCE_SUMMARY_COLUMNS + ", raw_output"


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
            existing_columns = {row["name"] for row in connection.execute("PRAGMA table_info(clips)")}
            for column, column_type in _ADDED_CLIP_COLUMNS.items():
                if column not in existing_columns:
                    connection.execute(f"ALTER TABLE clips ADD COLUMN {column} {column_type}")

    def add_clip(
        self,
        audio_filename: str,
        capture_info_json: str | None,
        started_at: str | None = None,
        ended_at: str | None = None,
    ) -> int:
        """Queue a newly uploaded clip for transcription.

        Args:
            audio_filename: Name of the WAV file in the recordings directory.
            capture_info_json: What the browser reported about the capture, as JSON text.
            started_at: When the clip's audio began (UTC ISO text), if the browser reported it.
            ended_at: When the clip's audio ended (UTC ISO text), if the browser reported it.

        Returns:
            The new clip's id.
        """
        with self._transaction() as connection:
            cursor = connection.execute(
                "INSERT INTO clips (created_at, started_at, ended_at, audio_filename, status, capture_info_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (utc_now_iso(), started_at, ended_at, audio_filename, constants.CLIP_STATUS_QUEUED, capture_info_json),
            )
            return int(cursor.lastrowid)

    def claim_next_queued_clip(self) -> dict[str, Any] | None:
        """Take the oldest queued clip and mark it as processing.

        Returns:
            ``{"id", "audio_filename"}`` for the claimed clip, or None if the queue is empty.
        """
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT id, audio_filename FROM clips WHERE status = ? ORDER BY id LIMIT 1",
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
        """Return clips left in "processing" (for example after a crash) to the queue.

        Returns:
            How many clips were requeued.
        """
        with self._transaction() as connection:
            cursor = connection.execute(
                "UPDATE clips SET status = ? WHERE status = ?",
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
    ) -> None:
        """Store a finished clip's measurements and utterances, replacing earlier ones.

        Args:
            clip_id: Clip that was processed.
            analysis: Loudness, pauses, and turns measured for the clip.
            utterances: Transcribed turns.
            whisper_model: Name of the model that produced the text.
            transcribe_seconds: Total processing time for the clip.
        """
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
                "analysis_params_json = ?, whisper_model = ?, transcribe_seconds = ?, processed_at = ? WHERE id = ?",
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
                    clip_id,
                ),
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
                "UPDATE clips SET status = ?, error_message = NULL WHERE id = ?",
                (constants.CLIP_STATUS_QUEUED, clip_id),
            )
            return True

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

    def list_clips(self, limit: int | None = None, newest_first: bool = True) -> list[dict[str, Any]]:
        """List clips with their utterances (without the bulky measurement data).

        Args:
            limit: Maximum number of clips, or None for all.
            newest_first: Sort newest first (True) or oldest first (False).

        Returns:
            Clip dictionaries, each with an ``utterances`` list and a ``group_id``
            (clips that follow each other closely share a group).
        """
        order = "DESC" if newest_first else "ASC"
        query = f"SELECT {_CLIP_SUMMARY_COLUMNS} FROM clips ORDER BY id {order}"
        parameters: tuple[Any, ...] = ()
        if limit is not None:
            query += " LIMIT ?"
            parameters = (limit,)
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
        assign_conversation_groups(clips)
        return {"exported_at": utc_now_iso(), constants.RESPONSE_KEY_CLIPS: clips}

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
