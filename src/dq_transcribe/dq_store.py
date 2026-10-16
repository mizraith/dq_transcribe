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
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from dq_transcribe import constants
from dq_transcribe.call_parser import CandidateCall, choose_codes, load_phrases, parse_call_group, stroke_clues
from dq_transcribe.database import Database, utc_now_iso
from dq_transcribe.meet_files.model import normalize_event_number
from dq_transcribe.meet_files.store import MeetProgramStore
from dq_transcribe.slip_codes import load_dq_codes, rank_codes  # load_dq_codes is re-exported for the server

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


class DqStore:
    """DQ records in the app database."""

    def __init__(self, database: Database, program_store: MeetProgramStore | None = None) -> None:
        """Use the app's database (call ``initialize`` once at start-up).

        Args:
            database: The app database.
            program_store: Loaded Meet Manager files, used to fill in swimmer and
                club from event/heat/lane and to know each event's stroke. Optional.
        """
        self._database = database
        self._program_store = program_store
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
            existing = {row["name"] for row in connection.execute("PRAGMA table_info(dqs)")}
            for column, column_type in _ADDED_DQ_COLUMNS.items():
                if column not in existing:
                    connection.execute(f"ALTER TABLE dqs ADD COLUMN {column} {column_type}")

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
        strokes_from_file = self._program_store.event_strokes(meet_id) if self._program_store else {}
        results: list[dict[str, Any]] = []
        for group_id, call in parsed:
            if call.event in event_strokes:
                choose_codes(call, event_strokes[call.event], stroke_is_certain=call.event in strokes_from_file)
            key = candidate_key(call)
            if key not in used:
                results.append({**call.to_dict(), "key": key, "group_id": group_id})
        self._add_program_details(results, meet_id)
        return results

    def _event_strokes(self, meet_id: int | None, calls: list[CandidateCall]) -> dict[str, str]:
        """Each event's stroke: from the meet file when loaded, otherwise where the
        calls and saved DQs agree (events with mixed clues, such as an IM, are left out)."""
        from_file = self._program_store.event_strokes(meet_id) if self._program_store else {}
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
        learned = {event: next(iter(strokes)) for event, strokes in clues.items() if len(strokes) == 1}
        return {**learned, **from_file}

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
        self._fill_from_program(dq_id)
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
        self._fill_from_program(dq_id)
        return True

    def _fill_from_program(self, dq_id: int) -> None:
        """Fill in an empty swimmer and club from the meet file (event, heat and lane).

        Only empty fields are filled: a name the admin typed is never replaced.
        """
        if self._program_store is None:
            return
        with self._database.transaction() as connection:
            row = connection.execute("SELECT meet_id, event, heat, lane, swimmer, club FROM dqs WHERE id = ?", (dq_id,)).fetchone()
            if row is None or (row["swimmer"] and row["club"]):
                return
            entry = self._program_store.lookup(row["meet_id"], row["event"], row["heat"], row["lane"])
            if entry is None:
                return
            connection.execute(
                "UPDATE dqs SET swimmer = COALESCE(swimmer, ?), club = COALESCE(club, ?) WHERE id = ?",
                (entry["swimmer"], entry["club"] or None, dq_id),
            )

    def change_state(
        self, dq_id: int, state: str, by_name: str | None = None, note: str | None = None, at: str | None = None
    ) -> bool:
        """Move a DQ to a new state, recording who and when in the history.

        Some states record more:

        * ``notified``: when and by whom (``notified_at``, ``notified_by``).
        * ``protested``: when the protest came in (``at``, default now) and the
          protest count. A protest after the window (30 minutes from the call) or
          beyond the cycle limit is accepted only with a reason in ``note``: the
          app never makes it impossible, it asks why.
        * ``upheld`` / ``overturned``: who ruled (``ruled_by``).

        Args:
            dq_id: The DQ.
            state: One of ``constants.DQ_STATES``.
            by_name: Who made the change (a person or, for notification, a channel).
            note: Free text kept in the history (required for late or extra protests).
            at: When it happened, ISO text (default: now).

        Returns:
            False if there is no such DQ.

        Raises:
            DqError: If the state or time is invalid, or a late/extra protest has no reason.
        """
        if state not in constants.DQ_STATES:
            raise DqError(f"Unknown state {state!r}")
        when = _parse_time(at) if at else datetime.now(timezone.utc)
        when_text = when.isoformat(timespec="seconds")
        with self._database.transaction() as connection:
            row = connection.execute("SELECT state, protest_count FROM dqs WHERE id = ?", (dq_id,)).fetchone()
            if row is None:
                return False
            extra = ""
            values: list[Any] = []
            if state == constants.DQ_STATE_NOTIFIED:
                extra, values = ", notified_at = ?, notified_by = ?", [when_text, by_name]
            elif state == constants.DQ_STATE_PROTESTED:
                count = row["protest_count"] or 0
                deadline = _protest_deadline(_call_time(connection, dq_id))
                if not note and count >= constants.MAX_PROTEST_CYCLES:
                    raise DqError(f"This DQ already had {count} protests (limit {constants.MAX_PROTEST_CYCLES}). Add a reason to accept another.")
                if not note and deadline is not None and when > deadline:
                    raise DqError(f"The protest window closed at {_local_clock(deadline)}. Add a reason to accept a late protest.")
                extra, values = ", protested_at = ?, protest_count = ?", [when_text, count + 1]
            elif state in (constants.DQ_STATE_UPHELD, constants.DQ_STATE_OVERTURNED):
                extra, values = ", ruled_by = ?", [by_name]
            connection.execute(f"UPDATE dqs SET state = ?, updated_at = ?{extra} WHERE id = ?", (state, utc_now_iso(), *values, dq_id))
            connection.execute(
                "INSERT INTO dq_history (dq_id, at, from_state, to_state, by_name, note) VALUES (?, ?, ?, ?, ?, ?)",
                (dq_id, when_text, row["state"], state, by_name, note),
            )
            return True

    def create_dq_from_utterance(self, utterance_id: int, selected_text: str | None = None) -> list[int]:
        """Make DQs by hand from one transcript line (for calls the detector missed).

        The line (or just the words the admin selected in it) is read by the call
        parser, so event, heat, lane, infraction and slip code are filled in where
        it can; one DQ is made per lane found, or one DQ with only the audio linked
        if nothing was understood. The audio of the line is linked as evidence and
        the words are kept in the DQ's notes.

        Args:
            utterance_id: The transcript line.
            selected_text: Words selected in the line (default: the whole line).

        Returns:
            The new DQ ids (empty if there is no such line).
        """
        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT u.id, u.clip_id, u.start_seconds, u.end_seconds, u.text, c.meet_id FROM utterances u "
                "JOIN clips c ON c.id = u.clip_id WHERE u.id = ?",
                (utterance_id,),
            ).fetchone()
        if row is None:
            return []
        text = (selected_text or "").strip() or row["text"] or ""
        utterance = {"clip_id": row["clip_id"], "id": row["id"], "start_seconds": row["start_seconds"],
                     "end_seconds": row["end_seconds"], "text": text}
        calls = [call for call in parse_call_group([utterance], self._phrases) if call.lane or call.infractions]
        meet_id = row["meet_id"]
        event_strokes = self._event_strokes(meet_id, calls)
        strokes_from_file = self._program_store.event_strokes(meet_id) if self._program_store else {}
        evidence = [{"clip_id": row["clip_id"], "utterance_id": row["id"], "start_seconds": row["start_seconds"],
                     "end_seconds": row["end_seconds"], "role": constants.EVIDENCE_ROLE_CALL}]
        note = constants.MANUAL_DQ_NOTE_FORMAT.format(text=text[: constants.MAX_DQ_FIELD_CHARS - 40])
        payloads = []
        for call in calls:
            if call.event in event_strokes:
                choose_codes(call, event_strokes[call.event], stroke_is_certain=call.event in strokes_from_file)
            payloads.append({
                "event": call.event, "heat": call.heat, "lane": call.lane, "notes": note, "evidence": evidence,
                "infractions": [
                    {"description": description, "code": code, "phases": call.phases,
                     "code_options": options or call.suggested_codes}
                    for description, code, options in zip(call.infractions, call.codes, call.code_options)
                ],
            })
        if not payloads:
            payloads.append({"notes": note, "evidence": evidence, "infractions": []})
        return [self.create_dq(payload, meet_id) for payload in payloads]

    def delete_declined(self, meet_id: int) -> int:
        """Permanently delete a closed meet's declined DQs (the trash). Overturned DQs are never deleted.

        Returns:
            How many were deleted.
        """
        with self._database.transaction() as connection:
            ids = [row["id"] for row in connection.execute(
                "SELECT id FROM dqs WHERE meet_id = ? AND state = ?", (meet_id, constants.DQ_STATE_DECLINED))]
            for dq_id in ids:
                for table in ("dq_infractions", "dq_evidence", "dq_history"):
                    connection.execute(f"DELETE FROM {table} WHERE dq_id = ?", (dq_id,))
                connection.execute("DELETE FROM dqs WHERE id = ?", (dq_id,))
            return len(ids)

    def notify_event(self, meet_id: int | None, event: str, by_name: str | None, include_not_ready: bool = False) -> list[int]:
        """Notify every DQ of an event that is pending notification (the paper process:
        slips go to the coaches once all of the event's DQs are complete).

        Args:
            meet_id: The meet.
            event: The event number.
            by_name: Who or what notified (see ``constants.NOTIFIED_BY_OPTIONS``).
            include_not_ready: Notify the ready ones even though others in the
                event are still called or incomplete.

        Returns:
            The ids of the DQs notified.

        Raises:
            DqError: If the event is not ready (and ``include_not_ready`` is false) or has nothing to notify.
        """
        dqs = [dq for dq in self.list_dqs(meet_id) if (dq["event"] or "") == event]
        ready = [dq for dq in dqs if dq["status"] == constants.DQ_STATUS_PENDING_NOTIFICATION]
        waiting = [dq for dq in dqs if dq["status"] in (constants.DQ_STATUS_CALLED, constants.DQ_STATUS_INCOMPLETE)]
        if waiting and not include_not_ready:
            raise DqError(f"Event {event} is not ready: {len(waiting)} DQ(s) still called or incomplete")
        if not ready:
            raise DqError(f"Event {event} has no DQs pending notification")
        for dq in ready:
            self.change_state(dq["id"], constants.DQ_STATE_NOTIFIED, by_name)
        return [dq["id"] for dq in ready]

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
                heard = " ".join(
                    row["text"] or ""
                    for row in connection.execute(
                        "SELECT u.text FROM dq_evidence e JOIN utterances u ON u.id = e.utterance_id WHERE e.dq_id = ?",
                        (dq["id"],),
                    )
                )
                _suggest_codes(dq, heard)
                call_time = _call_time(connection, dq["id"])
                deadline = _protest_deadline(call_time)
                dq["call_time"] = call_time.isoformat(timespec="seconds") if call_time else None
                dq["protest_deadline"] = deadline.isoformat(timespec="seconds") if deadline else None
                dq["missing"] = missing_fields(dq)
                dq["status"] = dq_status(dq["state"], dq["missing"])
                dq["history"] = [
                    dict(row)
                    for row in connection.execute(
                        "SELECT at, from_state, to_state, by_name, note FROM dq_history WHERE dq_id = ? ORDER BY id",
                        (dq["id"],),
                    )
                ]
        self._add_program_details(dqs, meet_id)
        dqs.sort(key=lambda dq: (number_sort_key(dq["event"]), number_sort_key(dq["heat"]), number_sort_key(dq["lane"]), dq["id"]))
        return dqs

    def _add_program_details(self, items: list[dict[str, Any]], meet_id: int | None) -> None:
        """Add ``event_label`` (from the meet file) and, for DQs, ``lookup`` and ``lookup_differs``.

        ``lookup_differs`` is true when the meet file names a different swimmer than
        the DQ, for example after a newer file was loaded: the admin confirms it.
        """
        if self._program_store is None:
            return
        events = self._program_store.events(meet_id)
        for item in items:
            event = events.get(normalize_event_number(item["event"])) if item.get("event") else None
            item["event_label"] = _event_label(event)
            if "swimmer" not in item:
                continue
            lookup = self._program_store.lookup(item.get("meet_id", meet_id), item["event"], item["heat"], item["lane"])
            item["lookup"] = lookup
            item["lookup_differs"] = bool(lookup and item["swimmer"] and item["swimmer"] != lookup["swimmer"])


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


# Columns added to dqs after the first release (added on start-up if missing).
_ADDED_DQ_COLUMNS = {
    "notified_at": "TEXT", "notified_by": "TEXT", "protested_at": "TEXT",
    "protest_count": "INTEGER NOT NULL DEFAULT 0", "ruled_by": "TEXT",
}


def _parse_time(text: str) -> datetime:
    """Read an ISO time (a time without a zone is taken as this device's local time)."""
    try:
        moment = datetime.fromisoformat(text)
    except (TypeError, ValueError) as error:
        raise DqError(f"Not a time: {text!r}") from error
    return moment.astimezone(timezone.utc) if moment.tzinfo else moment.astimezone().astimezone(timezone.utc)


def _call_time(connection: sqlite3.Connection, dq_id: int) -> datetime | None:
    """When the DQ was called on the radio: the earliest evidence (clip start + offset).

    It stands in for the race time, which starts the protest window.
    """
    times = []
    for row in connection.execute(
        "SELECT COALESCE(c.started_at, c.created_at) AS clip_start, e.start_seconds FROM dq_evidence e "
        "JOIN clips c ON c.id = e.clip_id WHERE e.dq_id = ?",
        (dq_id,),
    ):
        try:
            start = datetime.fromisoformat(row["clip_start"])
        except (TypeError, ValueError):
            continue
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        times.append(start + timedelta(seconds=row["start_seconds"] or 0))
    return min(times) if times else None


def _protest_deadline(call_time: datetime | None) -> datetime | None:
    """When the protest window closes (rulebook 102.22.4: 30 minutes from the race)."""
    return call_time + timedelta(minutes=constants.PROTEST_WINDOW_MINUTES) if call_time else None


def _local_clock(moment: datetime) -> str:
    """A time as this device shows it, 12-hour ("5:42 PM")."""
    return moment.astimezone().strftime(constants.CLOCK_FORMAT_12_HOUR).lstrip("0")


def _event_label(event: dict[str, Any] | None) -> str | None:
    """"Girls 10 & Under 50 Breaststroke" for an event from the meet file."""
    if not event:
        return None
    parts = [event["gender"], event["age_group"], str(event["distance"]) if event["distance"] else None, event["stroke"]]
    return " ".join(part for part in parts if part) or event["description"]


def missing_fields(dq: dict[str, Any]) -> list[str]:
    """Required fields a DQ still lacks (``"infraction"`` if it has none)."""
    missing = [name for name in constants.DQ_REQUIRED_FIELDS if not dq.get(name)]
    if not dq.get("infractions"):
        missing.append(constants.DQ_REQUIRED_INFRACTION)
    return missing


def dq_status(state: str, missing: list[str]) -> str:
    """The status shown and filtered on: the state, with an accepted DQ split into
    "incomplete" (information missing) and "pending notification" (ready)."""
    if state == constants.DQ_STATE_ACCEPTED:
        return constants.DQ_STATUS_INCOMPLETE if missing else constants.DQ_STATUS_PENDING_NOTIFICATION
    return {
        constants.DQ_STATE_CALLED: constants.DQ_STATUS_CALLED,
        constants.DQ_STATE_NOTIFIED: constants.DQ_STATUS_NOTIFIED,
        constants.DQ_STATE_DECLINED: constants.DQ_STATUS_DECLINED,
    }.get(state, state)


def _suggest_codes(dq: dict[str, Any], heard: str) -> None:
    """Fill in likely slip codes: per infraction (if none were saved) and for the whole DQ.

    ``suggested_codes`` ranks the slip's lines against what was heard and the
    infraction descriptions; the editor offers it for an infraction with no
    options of its own (such as a newly added one).
    """
    codes = [infraction["code"] for infraction in dq["infractions"] if infraction["code"]]
    stroke = _CODE_PREFIX_TO_STROKE.get(codes[0][0]) if codes else None
    for infraction in dq["infractions"]:
        if not infraction["code_options"]:
            infraction["code_options"] = rank_codes(infraction["description"], stroke)
    dq["suggested_codes"] = rank_codes(" ".join([heard, *(item["description"] for item in dq["infractions"])]), stroke)


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
