"""DQ records: storage, detected-call suggestions, and the DQ slip code list.

A DQ never contains audio. It cites *evidence*: time ranges of utterances in
existing clips (the call, the referee's acknowledgment). Several DQs may cite the
same utterance (one call naming several lanes), and one DQ may cite several
clips. See ``ai_docs/product_plan.md`` section 4.3.

Detected calls ("candidates") are computed on request from the current
transcripts with ``call_parser`` and are never stored. Only two things are
stored about them: which candidate a DQ was created from (so it is not offered
again), and candidates the admin dismissed.

Tables (created by ``DqStore.initialize`` in the app's SQLite file):

* ``dqs``: one row per DQ (event, heat, lane, people, state, ...).
* ``dq_infractions``: the infractions of a DQ (description, code, phases, detail).
* ``dq_evidence``: the clip time ranges a DQ was heard in.
* ``dq_history``: every state change, with time and who (append-only).
* ``candidate_dismissals``: detected calls the admin dismissed.
"""

from __future__ import annotations

import copy
import csv
import json
import re
import sqlite3
from typing import Any

from dq_transcribe import constants
from dq_transcribe.call_parser import CandidateCall, choose_codes, load_phrases, parse_call_group, stroke_clues
from dq_transcribe.database import Database, utc_now_iso

_CREATE_TABLES = (
    """
    CREATE TABLE IF NOT EXISTS dqs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        meet_id INTEGER,
        event TEXT, heat TEXT, lane TEXT, relay_leg TEXT,
        swimmer TEXT, club TEXT,
        official TEXT, official_role TEXT, chief_judge TEXT, referee TEXT,
        state TEXT NOT NULL,
        source TEXT NOT NULL,
        candidate_key TEXT,
        notes TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS dq_infractions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dq_id INTEGER NOT NULL REFERENCES dqs(id) ON DELETE CASCADE,
        position INTEGER NOT NULL,
        description TEXT NOT NULL,
        code TEXT,
        slip_revision TEXT,
        phases TEXT,
        detail TEXT,
        code_options TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS dq_evidence (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dq_id INTEGER NOT NULL REFERENCES dqs(id) ON DELETE CASCADE,
        clip_id INTEGER NOT NULL,
        utterance_id INTEGER,
        start_seconds REAL NOT NULL,
        end_seconds REAL NOT NULL,
        role TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS dq_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dq_id INTEGER NOT NULL REFERENCES dqs(id) ON DELETE CASCADE,
        at TEXT NOT NULL,
        from_state TEXT,
        to_state TEXT NOT NULL,
        by_name TEXT,
        note TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS candidate_dismissals (
        candidate_key TEXT PRIMARY KEY,
        meet_id INTEGER,
        dismissed_at TEXT NOT NULL
    )
    """,
)
_EVENT_SORT_PATTERN = re.compile(r"^(\d+)(.*)$")
# Parsed calls are cached per conversation group and recomputed only when the
# group's turns or their text change (parsing every group on every page refresh
# was too slow on the tablet). The cache is cleared when it grows past this size.
_PARSE_CACHE_LIMIT = 2000
# The first character of a stroke's slip code (rev 2024-01): 1 butterfly, 2 back, 3 breast, 4 free.
_CODE_PREFIX_TO_STROKE = {"1": "Butterfly", "2": "Backstroke", "3": "Breaststroke", "4": "Freestyle"}
_UNKNOWN_SORT_VALUE = 10**9  # blanks sort last


class DqError(ValueError):
    """A DQ request had invalid data (the message says what)."""


def candidate_key(call: CandidateCall) -> str:
    """Stable key for a detected call: the first utterance it was heard in, plus its lane."""
    first_call = next((item for item in call.evidence if item.role == constants.EVIDENCE_ROLE_CALL), call.evidence[0])
    return f"{first_call.utterance_id}:{call.lane or '-'}"


def number_sort_key(value: str | None) -> tuple[int, str]:
    """Sort "2" < "2b" < "10"; blanks last."""
    if not value:
        return (_UNKNOWN_SORT_VALUE, "")
    match = _EVENT_SORT_PATTERN.match(value.strip())
    return (int(match.group(1)), match.group(2)) if match else (_UNKNOWN_SORT_VALUE, value)


def load_dq_codes(revision: str = constants.CURRENT_SLIP_REVISION) -> list[dict[str, str]]:
    """The DQ slip's code table for a revision (empty if the file is missing)."""
    path = constants.REFERENCE_DIRECTORY / "dq_codes" / constants.DQ_CODES_FILENAME_FORMAT.format(revision=revision)
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))
    except OSError:
        return []


class DqStore:
    """DQ records in the app database."""

    def __init__(self, database: Database) -> None:
        """Use the app's database (call ``initialize`` once at start-up)."""
        self._database = database
        self._phrases = load_phrases()
        self._parse_cache: dict[tuple, list[CandidateCall]] = {}

    def initialize(self) -> None:
        """Create the DQ tables if they do not exist, and add columns added since."""
        with self._database.connection() as connection:
            for statement in _CREATE_TABLES:
                connection.execute(statement)
            existing = {row["name"] for row in connection.execute("PRAGMA table_info(dq_infractions)")}
            if "code_options" not in existing:
                connection.execute("ALTER TABLE dq_infractions ADD COLUMN code_options TEXT")

    # --- Detected calls ------------------------------------------------------

    def candidates(self, meet_id: int | None) -> list[dict[str, Any]]:
        """Detected calls for a meet's clips, minus those already used or dismissed.

        Args:
            meet_id: Meet whose clips to read (None = all clips).

        Returns:
            Candidate dictionaries (see ``CandidateCall.to_dict``) plus ``key`` and
            ``group_id``, in time order.
        """
        clips = self._database.list_clips(newest_first=False, meet_id=meet_id)
        with self._database.connection() as connection:
            used = {row[0] for row in connection.execute("SELECT candidate_key FROM dqs WHERE candidate_key IS NOT NULL")}
            used |= {row[0] for row in connection.execute("SELECT candidate_key FROM candidate_dismissals")}
        groups: dict[int, list[dict[str, Any]]] = {}
        for clip in clips:
            groups.setdefault(clip["group_id"], []).append(clip)
        parsed: list[tuple[int, CandidateCall]] = []
        for group_id, group_clips in groups.items():
            utterances = [
                {
                    "clip_id": clip["id"],
                    "id": utterance["id"],
                    "start_seconds": utterance["start_seconds"],
                    "end_seconds": utterance["end_seconds"],
                    "text": utterance["text"],
                }
                for clip in sorted(group_clips, key=lambda item: item["id"])
                for utterance in clip["utterances"]
            ]
            parsed.extend((group_id, copy.deepcopy(call)) for call in self._parse_cached(utterances))
        # Every call in an event has the same stroke: learn each event's stroke from
        # the calls and saved DQs that reveal it, then use it for the other calls.
        event_strokes = self._event_strokes(meet_id, [call for _, call in parsed])
        results: list[dict[str, Any]] = []
        for group_id, call in parsed:
            if call.event in event_strokes:
                choose_codes(call, event_strokes[call.event])
            key = candidate_key(call)
            if key not in used:
                results.append({**call.to_dict(), "key": key, "group_id": group_id})
        return results

    def _event_strokes(self, meet_id: int | None, calls: list[CandidateCall]) -> dict[str, str]:
        """Each event's stroke where the evidence agrees (events with mixed clues, such as an IM, are left out)."""
        clues: dict[str, set[str]] = {}
        for call in calls:
            if call.event:
                clues.setdefault(call.event, set()).update(stroke_clues(call))
        for dq in self.list_dqs(meet_id):
            if not dq["event"]:
                continue
            for infraction in dq["infractions"]:
                stroke = _CODE_PREFIX_TO_STROKE.get((infraction["code"] or " ")[0])
                if stroke:
                    clues.setdefault(dq["event"], set()).add(stroke)
        return {event: next(iter(strokes)) for event, strokes in clues.items() if len(strokes) == 1}

    def _parse_cached(self, utterances: list[dict[str, Any]]) -> list[CandidateCall]:
        """Parse a group's turns, reusing the last result if nothing in the group changed."""
        signature = tuple((item["id"], item["clip_id"], item["start_seconds"], item["end_seconds"], item["text"]) for item in utterances)
        calls = self._parse_cache.get(signature)
        if calls is None:
            if len(self._parse_cache) >= _PARSE_CACHE_LIMIT:
                self._parse_cache.clear()
            calls = parse_call_group(utterances, self._phrases)
            self._parse_cache[signature] = calls
        return calls

    def dismiss_candidate(self, key: str, meet_id: int | None) -> None:
        """Hide a detected call (it can be recreated by hand if needed)."""
        with self._database.transaction() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO candidate_dismissals (candidate_key, meet_id, dismissed_at) VALUES (?, ?, ?)",
                (key, meet_id, utc_now_iso()),
            )

    # --- DQs ---------------------------------------------------------------

    def create_dq(self, payload: dict[str, Any], meet_id: int | None) -> int:
        """Create a DQ from a detected call or by hand.

        Args:
            payload: Text fields (see ``constants.DQ_TEXT_FIELDS``), ``infractions``
                (list of {description, code, phases, detail}), ``evidence`` (list of
                {clip_id, utterance_id, start_seconds, end_seconds, role}),
                ``accepted`` (bool) and optionally ``candidate_key``.
            meet_id: Meet the DQ belongs to.

        Returns:
            The new DQ's id.

        Raises:
            DqError: If the payload is invalid.
        """
        fields = _text_fields(payload)
        infractions = _infractions(payload.get(constants.REQUEST_KEY_INFRACTIONS, []))
        evidence = _evidence(payload.get(constants.REQUEST_KEY_EVIDENCE, []))
        key = payload.get(constants.REQUEST_KEY_CANDIDATE_KEY)
        state = constants.DQ_STATE_ACCEPTED if payload.get("accepted") else constants.DQ_STATE_CALLED
        source = constants.DQ_SOURCE_AUTO if key else constants.DQ_SOURCE_MANUAL
        now = utc_now_iso()
        with self._database.transaction() as connection:
            columns = ", ".join(fields)
            placeholders = ", ".join("?" for _ in fields)
            cursor = connection.execute(
                f"INSERT INTO dqs (meet_id, state, source, candidate_key, created_at, updated_at"
                f"{', ' + columns if fields else ''}) VALUES (?, ?, ?, ?, ?, ?{', ' + placeholders if fields else ''})",
                (meet_id, state, source, key if isinstance(key, str) else None, now, now, *fields.values()),
            )
            dq_id = int(cursor.lastrowid)
            _replace_infractions(connection, dq_id, infractions)
            connection.executemany(
                "INSERT INTO dq_evidence (dq_id, clip_id, utterance_id, start_seconds, end_seconds, role) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [(dq_id, *item) for item in evidence],
            )
            connection.execute(
                "INSERT INTO dq_history (dq_id, at, from_state, to_state, by_name, note) VALUES (?, ?, NULL, ?, ?, ?)",
                (dq_id, now, state, None, "created from a detected call" if key else "created by hand"),
            )
            return dq_id

    def update_dq(self, dq_id: int, payload: dict[str, Any]) -> bool:
        """Change a DQ's text fields and/or replace its infractions.

        Returns:
            False if there is no such DQ.

        Raises:
            DqError: If the payload is invalid.
        """
        fields = _text_fields(payload)
        infractions = (
            _infractions(payload[constants.REQUEST_KEY_INFRACTIONS])
            if constants.REQUEST_KEY_INFRACTIONS in payload
            else None
        )
        with self._database.transaction() as connection:
            if connection.execute("SELECT 1 FROM dqs WHERE id = ?", (dq_id,)).fetchone() is None:
                return False
            assignments = ", ".join(f"{name} = ?" for name in fields)
            connection.execute(
                f"UPDATE dqs SET updated_at = ?{', ' + assignments if fields else ''} WHERE id = ?",
                (utc_now_iso(), *fields.values(), dq_id),
            )
            if infractions is not None:
                _replace_infractions(connection, dq_id, infractions)
            return True

    def change_state(self, dq_id: int, state: str, by_name: str | None = None, note: str | None = None) -> bool:
        """Move a DQ to a new state, recording who and when in the history.

        Returns:
            False if there is no such DQ.

        Raises:
            DqError: If the state is unknown.
        """
        if state not in constants.DQ_STATES:
            raise DqError(f"Unknown state {state!r}")
        with self._database.transaction() as connection:
            row = connection.execute("SELECT state FROM dqs WHERE id = ?", (dq_id,)).fetchone()
            if row is None:
                return False
            now = utc_now_iso()
            connection.execute("UPDATE dqs SET state = ?, updated_at = ? WHERE id = ?", (state, now, dq_id))
            connection.execute(
                "INSERT INTO dq_history (dq_id, at, from_state, to_state, by_name, note) VALUES (?, ?, ?, ?, ?, ?)",
                (dq_id, now, row["state"], state, by_name, note),
            )
            return True

    def list_dqs(self, meet_id: int | None) -> list[dict[str, Any]]:
        """A meet's DQs (all DQs if None), sorted by event, heat, lane, with infractions, evidence and history."""
        with self._database.connection() as connection:
            if meet_id is None:
                rows = connection.execute("SELECT * FROM dqs")
            else:
                rows = connection.execute("SELECT * FROM dqs WHERE meet_id = ?", (meet_id,))
            dqs = [dict(row) for row in rows]
            for dq in dqs:
                dq["infractions"] = [
                    {
                        **dict(row),
                        "phases": json.loads(row["phases"] or "[]"),
                        "code_options": json.loads(row["code_options"] or "[]"),
                    }
                    for row in connection.execute(
                        "SELECT description, code, slip_revision, phases, detail, code_options FROM dq_infractions "
                        "WHERE dq_id = ? ORDER BY position",
                        (dq["id"],),
                    )
                ]
                dq["evidence"] = [
                    dict(row)
                    for row in connection.execute(
                        "SELECT clip_id, utterance_id, start_seconds, end_seconds, role FROM dq_evidence "
                        "WHERE dq_id = ? ORDER BY clip_id, start_seconds",
                        (dq["id"],),
                    )
                ]
                dq["history"] = [
                    dict(row)
                    for row in connection.execute(
                        "SELECT at, from_state, to_state, by_name, note FROM dq_history WHERE dq_id = ? ORDER BY id",
                        (dq["id"],),
                    )
                ]
        dqs.sort(key=lambda dq: (number_sort_key(dq["event"]), number_sort_key(dq["heat"]), number_sort_key(dq["lane"]), dq["id"]))
        return dqs


# --- Validation helpers ------------------------------------------------------


def _text_fields(payload: dict[str, Any]) -> dict[str, str | None]:
    """The editable text fields present in a payload, validated."""
    fields: dict[str, str | None] = {}
    for name in constants.DQ_TEXT_FIELDS:
        if name not in payload:
            continue
        value = payload[name]
        if value is not None and not isinstance(value, (str, int)):
            raise DqError(f"{name} must be text")
        text = None if value is None else str(value).strip()
        if text is not None and len(text) > constants.MAX_DQ_FIELD_CHARS:
            raise DqError(f"{name} is too long")
        fields[name] = text or None
    return fields


def _infractions(items: Any) -> list[tuple[str, str | None, str | None, str, str | None, str]]:
    """Validated infraction rows: (description, code, slip_revision, phases_json, detail, code_options_json).

    ``code_options`` are the slip codes this infraction could be (for example
    ["1J", "3J"] for a one hand touch); the code picker lists them first.
    """
    if not isinstance(items, list):
        raise DqError("infractions must be a list")
    rows = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("description"), str) or not item["description"].strip():
            raise DqError("each infraction needs a description")
        phases = item.get("phases") or []
        if not isinstance(phases, list) or any(phase not in constants.RACE_PHASES for phase in phases):
            raise DqError(f"phases must be some of {', '.join(constants.RACE_PHASES)}")
        code = item.get("code") or None
        options = item.get("code_options") or []
        if not isinstance(options, list) or not all(isinstance(option, str) for option in options):
            raise DqError("code_options must be a list of codes")
        rows.append(
            (
                item["description"].strip()[: constants.MAX_DQ_FIELD_CHARS],
                str(code) if code else None,
                str(item.get("slip_revision") or constants.CURRENT_SLIP_REVISION) if code else None,
                json.dumps(phases),
                (str(item["detail"])[: constants.MAX_DQ_FIELD_CHARS] if item.get("detail") else None),
                json.dumps(options[:20]),
            )
        )
    return rows


def _evidence(items: Any) -> list[tuple[int, int | None, float, float, str]]:
    """Validated evidence rows: (clip_id, utterance_id, start_seconds, end_seconds, role)."""
    if not isinstance(items, list):
        raise DqError("evidence must be a list")
    rows = []
    for item in items:
        try:
            role = item.get("role", constants.EVIDENCE_ROLE_CALL)
            if role not in constants.EVIDENCE_ROLES:
                raise DqError(f"unknown evidence role {role!r}")
            utterance_id = item.get("utterance_id")
            rows.append(
                (
                    int(item["clip_id"]),
                    None if utterance_id is None else int(utterance_id),
                    float(item["start_seconds"]),
                    float(item["end_seconds"]),
                    role,
                )
            )
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise DqError(f"bad evidence item: {error}") from error
    return rows


def _replace_infractions(connection: sqlite3.Connection, dq_id: int, rows: list[tuple]) -> None:
    """Replace a DQ's infractions (inside the caller's transaction)."""
    connection.execute("DELETE FROM dq_infractions WHERE dq_id = ?", (dq_id,))
    connection.executemany(
        "INSERT INTO dq_infractions (dq_id, position, description, code, slip_revision, phases, detail, code_options) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [(dq_id, position, *row) for position, row in enumerate(rows)],
    )
