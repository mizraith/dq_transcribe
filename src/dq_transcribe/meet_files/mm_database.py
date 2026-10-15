"""Read the Hy-Tek Meet Manager database (a backup .zip, or the .mdb inside it).

Meet Manager keeps a meet in a Microsoft Access database (``.mdb``); its backup
is a ``.zip`` holding that file. The tables are read with ``mdb-export`` from
mdbtools (Termux: ``pkg install mdbtools``) as CSV.

**Unverified:** the table and column names below are Meet Manager's usual ones
(Event, Athlete, Team, Entry, Relay, RelayNames, Session, Sessitem, Meet), written
from documentation and other tools, not yet checked against the owner's file.
Column names are matched without regard to case, and several known spellings are
tried, so small differences do not break the import. Once the real file arrives,
fix anything listed in the program's warnings.

Codes used by Meet Manager:

* ``Event_stroke``: A Freestyle, B Backstroke, C Breaststroke, D Butterfly,
  E Individual Medley (for relays: A Freestyle Relay, E Medley Relay).
* ``Ind_rel``: I individual, R relay.
* ``Event_sex``: F/G female, M/B male, X mixed.
"""

from __future__ import annotations

import csv
import io
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from dq_transcribe import constants
from dq_transcribe.meet_files.errors import MeetFileError
from dq_transcribe.meet_files.model import (
    MeetProgram,
    ProgramEntry,
    ProgramEvent,
    ProgramSession,
    club_code,
    format_swimmer_name,
    normalize_event_number,
)

DATABASE_EXTENSIONS = (".mdb", ".accdb")
NO_DATABASE_READER_MESSAGE = (
    "Can't read the Meet Manager database yet: install the reader once (in Termux: pkg install mdbtools)."
)
NO_DATABASE_IN_ZIP_MESSAGE = "This .zip has no Meet Manager database (.mdb) inside."
INDIVIDUAL_STROKES = {
    "A": constants.STROKE_FREESTYLE, "B": constants.STROKE_BACKSTROKE, "C": constants.STROKE_BREASTSTROKE,
    "D": constants.STROKE_BUTTERFLY, "E": constants.STROKE_INDIVIDUAL_MEDLEY,
}
RELAY_STROKES = {"A": constants.STROKE_FREESTYLE_RELAY, "E": constants.STROKE_MEDLEY_RELAY}
RELAY_CODE = "R"
GENDER_WORDS = {"F": ("Girls", "Women"), "G": ("Girls", "Women"), "W": ("Girls", "Women"),
                "M": ("Boys", "Men"), "B": ("Boys", "Men"), "X": ("Mixed", "Mixed")}
# Ages above this are adult age groups (Women/Men instead of Girls/Boys).
YOUTH_MAX_AGE = 18
# Meet Manager stores "no upper age" as a large number.
NO_UPPER_AGE = 99
RELAY_TEAM_FORMAT = "{club}-{letter}"
MISSING_TABLE_WARNING = "The database has no {table} table (looked for: {names})."

# Tables and columns, with the spellings tried (first match wins, case ignored).
TABLE_NAMES = {
    "event": ("Event",), "athlete": ("Athlete",), "team": ("Team",), "entry": ("Entry",),
    "relay": ("Relay",), "relay_names": ("RelayNames", "Relaynames"), "session": ("Session",),
    "session_item": ("Sessitem", "SessItem", "Session_item"), "meet": ("Meet",),
}
COLUMNS = {
    "event_ptr": ("Event_ptr",), "event_no": ("Event_no",), "event_letter": ("Event_ltr",),
    "event_sex": ("Event_sex", "Event_gender"), "event_distance": ("Event_dist",),
    "event_stroke": ("Event_stroke",), "low_age": ("Low_age",), "high_age": ("High_Age", "High_age"),
    "individual_relay": ("Ind_rel",), "athlete_no": ("Ath_no",), "last_name": ("Last_name",),
    "first_name": ("First_name",), "preferred_name": ("Pref_name",), "athlete_age": ("Ath_age",),
    "team_no": ("Team_no",), "team_abbr": ("Team_abbr",), "team_name": ("Team_name",),
    "final_heat": ("Fin_heat",), "final_lane": ("Fin_lane",), "prelim_heat": ("Pre_heat",),
    "prelim_lane": ("Pre_lane",), "team_letter": ("Team_ltr",), "relay_no": ("Relay_no",),
    "position": ("Pos_no", "Relay_leg"), "session_no": ("Sess_no",), "session_ptr": ("Sess_ptr",),
    "session_name": ("Sess_name",), "session_day": ("Sess_day",), "session_start": ("Sess_starttime",),
    "meet_name": ("Meet_name1", "Meet_name"),
}
SECONDS_PER_HOUR = 3600
SECONDS_PER_MINUTE = 60


def _column(row: dict[str, str], key: str) -> str:
    """A row's value for a logical column (empty if the column is missing)."""
    lowered = {name.lower(): value for name, value in row.items()}
    for name in COLUMNS[key]:
        if name.lower() in lowered:
            return (lowered[name.lower()] or "").strip()
    return ""


def _positive_int(text: str) -> int:
    """Parse a heat/lane/number column ("0" or empty = not set)."""
    try:
        return int(float(text))
    except ValueError:
        return 0


def age_group_label(low: int, high: int) -> str | None:
    """Meet Manager ages as an age-group label: "10 & Under", "11-12", "13 & Over", "Open"."""
    if low <= 0 and (high <= 0 or high >= NO_UPPER_AGE):
        return "Open"
    if low <= 0:
        return f"{high} & Under"
    if high <= 0 or high >= NO_UPPER_AGE:
        return f"{low} & Over"
    return f"{low}-{high}"


def _start_time(text: str) -> str | None:
    """A session start time: Meet Manager stores seconds after midnight (or text)."""
    if not text:
        return None
    try:
        seconds = int(float(text))
    except ValueError:
        return text
    return f"{seconds // SECONDS_PER_HOUR:02d}:{seconds % SECONDS_PER_HOUR // SECONDS_PER_MINUTE:02d}"


class _AccessReader:
    """Read tables of an Access database through mdbtools."""

    def __init__(self, path: Path) -> None:
        if not shutil.which(constants.MDB_EXPORT_COMMAND):
            raise MeetFileError(NO_DATABASE_READER_MESSAGE)
        self._path = path
        self._tables = self._list_tables()

    def _run(self, *arguments: str) -> str:
        result = subprocess.run(
            list(arguments), capture_output=True, timeout=constants.EXTERNAL_COMMAND_TIMEOUT_SECONDS, check=False
        )
        if result.returncode != 0:
            raise MeetFileError(f"Could not read the database: {result.stderr.decode(errors='replace').strip()[:200]}")
        return result.stdout.decode("utf-8", errors="replace")

    def _list_tables(self) -> list[str]:
        output = self._run(constants.MDB_TABLES_COMMAND, "-1", str(self._path))
        return [line.strip() for line in output.splitlines() if line.strip()]

    def table(self, key: str, warnings: list[str]) -> list[dict[str, str]]:
        """Rows of a logical table, or [] (with a warning) if it is missing."""
        wanted = {name.lower() for name in TABLE_NAMES[key]}
        name = next((table for table in self._tables if table.lower() in wanted), None)
        if name is None:
            warnings.append(MISSING_TABLE_WARNING.format(table=key, names=", ".join(TABLE_NAMES[key])))
            return []
        return list(csv.DictReader(io.StringIO(self._run(constants.MDB_EXPORT_COMMAND, str(self._path), name))))


def read_meet_manager_database(path: Path) -> MeetProgram:
    """Read events, heats, entries and sessions from a Meet Manager backup or database.

    Args:
        path: A ``.zip`` backup (the database inside is used) or an ``.mdb`` file.

    Raises:
        MeetFileError: If the reader is not installed or the file is not a Meet Manager database.
    """
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive, tempfile.TemporaryDirectory() as folder:
            names = [name for name in archive.namelist() if name.lower().endswith(DATABASE_EXTENSIONS)]
            if not names:
                raise MeetFileError(NO_DATABASE_IN_ZIP_MESSAGE)
            extracted = Path(archive.extract(names[0], folder))
            return _read_database(extracted)
    return _read_database(path)


def _read_database(path: Path) -> MeetProgram:
    """Read an extracted ``.mdb``."""
    reader = _AccessReader(path)
    program = MeetProgram()
    warnings = program.warnings
    meets = reader.table("meet", warnings)
    if meets:
        program.meet_name = _column(meets[0], "meet_name")

    teams = {_column(row, "team_no"): club_code(_column(row, "team_abbr") or _column(row, "team_name")) for row in reader.table("team", warnings)}
    athletes: dict[str, dict[str, Any]] = {}
    for row in reader.table("athlete", warnings):
        first = _column(row, "preferred_name") or _column(row, "first_name")
        athletes[_column(row, "athlete_no")] = {
            "name": format_swimmer_name(first, _column(row, "last_name")),
            "club": teams.get(_column(row, "team_no"), ""),
            "age": _positive_int(_column(row, "athlete_age")) or None,
        }

    events_by_pointer: dict[str, ProgramEvent] = {}
    for row in reader.table("event", warnings):
        relay = _column(row, "individual_relay").upper() == RELAY_CODE
        stroke_code = _column(row, "event_stroke").upper()
        stroke = (RELAY_STROKES if relay else INDIVIDUAL_STROKES).get(stroke_code)
        low, high = _positive_int(_column(row, "low_age")), _positive_int(_column(row, "high_age"))
        youth_word, adult_word = GENDER_WORDS.get(_column(row, "event_sex").upper()[:1], ("", ""))
        gender = youth_word if 0 < high <= YOUTH_MAX_AGE or (high <= 0 and low <= YOUTH_MAX_AGE) else adult_word
        distance = _positive_int(_column(row, "event_distance")) or None
        age_group = age_group_label(low, high)
        number = normalize_event_number(_column(row, "event_no") + _column(row, "event_letter"))
        description = " ".join(part for part in (gender, age_group, str(distance or ""), stroke or "") if part)
        events_by_pointer[_column(row, "event_ptr")] = ProgramEvent(
            number=number, description=description, gender=gender or None, age_group=age_group,
            distance=distance, stroke=stroke, relay=relay,
        )

    for row in reader.table("entry", warnings):
        event = events_by_pointer.get(_column(row, "event_ptr"))
        athlete = athletes.get(_column(row, "athlete_no"))
        if event is None or athlete is None:
            continue
        for heat_key, lane_key, round_name in (("prelim_heat", "prelim_lane", "Prelims"), ("final_heat", "final_lane", None)):
            heat, lane = _positive_int(_column(row, heat_key)), _positive_int(_column(row, lane_key))
            if heat and lane:
                program.entries.append(ProgramEntry(
                    event_number=event.number, heat=str(heat), lane=str(lane), swimmer=athlete["name"],
                    club=athlete["club"], age=athlete["age"], round=round_name,
                ))

    relay_swimmers: dict[str, list[tuple[int, str]]] = {}
    for row in reader.table("relay_names", warnings):
        athlete = athletes.get(_column(row, "athlete_no"))
        if athlete:
            relay_swimmers.setdefault(_column(row, "relay_no"), []).append((_positive_int(_column(row, "position")), athlete["name"]))
    for row in reader.table("relay", warnings):
        event = events_by_pointer.get(_column(row, "event_ptr"))
        if event is None:
            continue
        club = teams.get(_column(row, "team_no"), "")
        name = RELAY_TEAM_FORMAT.format(club=club, letter=_column(row, "team_letter") or "A")
        swimmers = [swimmer for _, swimmer in sorted(relay_swimmers.get(_column(row, "relay_no"), []))]
        for heat_key, lane_key, round_name in (("prelim_heat", "prelim_lane", "Prelims"), ("final_heat", "final_lane", None)):
            heat, lane = _positive_int(_column(row, heat_key)), _positive_int(_column(row, lane_key))
            if heat and lane:
                program.entries.append(ProgramEntry(
                    event_number=event.number, heat=str(heat), lane=str(lane), swimmer=name, club=club,
                    relay=True, relay_swimmers=swimmers, round=round_name,
                ))

    sessions_by_pointer: dict[str, ProgramSession] = {}
    for row in reader.table("session", warnings):
        session = ProgramSession(
            number=_column(row, "session_no"), name=_column(row, "session_name"),
            day=_column(row, "session_day") or None, start_time=_start_time(_column(row, "session_start")),
        )
        sessions_by_pointer[_column(row, "session_ptr") or session.number] = session
    for row in reader.table("session_item", warnings):
        session = sessions_by_pointer.get(_column(row, "session_ptr"))
        event = events_by_pointer.get(_column(row, "event_ptr"))
        if session and event:
            session.event_numbers.append(event.number)
            event.session = event.session or session.number
    program.events = sorted(events_by_pointer.values(), key=lambda event: _event_sort_key(event.number))
    program.sessions = list(sessions_by_pointer.values())
    return program


def _event_sort_key(number: str) -> tuple[int, str]:
    """Sort "2", "2b", "10" in meet order."""
    digits = "".join(character for character in number if character.isdigit())
    return (int(digits) if digits else 0, number)
