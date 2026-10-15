"""Read a Hy-Tek Meet Manager report (heat sheet, meet program, psych sheet) from text.

The PDF and HTML importers both turn their file into plain text lines and hand
them to ``parse_report_lines``, so one parser covers every printed report.

What a heat sheet looks like (Hy-Tek prints these with small variations)::

    Event 12  Girls 10 & Under 50 Yard Breaststroke
      Lane  Name                     Age Team                   Seed Time
    Heat 1 of 3  Timed Finals                        Starts at 10:15 AM
        1  Smith, Jane M             10 Pleasanton Seahawks-PC      45.12Y
        2  Doe, Ann                   9 SCSC-PC                     NT

    Event 13  Boys 10 & Under 200 Yard Medley Relay
    Heat 1 of 2  Timed Finals
        3  Pleasanton Seahawks-PC         A                      2:45.10
             1) Lee, Pat 10           2) Kim, Sam 9
             3) Ruiz, Max 10          4) Park, Ben 10

A psych sheet or entry list has the same event headers but no heats: its lines
start with a seed rank instead of a lane, and are kept without heat and lane
(still useful for the event list and each swimmer's club).

Two-column PDF pages are split into columns first (``split_columns``).

The patterns are written from Hy-Tek's usual layout and must be checked against
the owner's real reports; anything not understood is counted in the warnings.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from dq_transcribe.meet_files.model import (
    MeetProgram,
    ProgramEntry,
    ProgramEvent,
    ProgramSession,
    club_code,
    format_swimmer_name,
    normalize_event_number,
)

_SEED = r"(?:NT|NS|SCR|X?\d{0,2}:?\d{1,2}\.\d{2}\s?[YLSM]?)"
EVENT_HEADER = re.compile(r"^\s*(?:Event|#)\s*(?P<number>\d{1,3}[A-Za-z]?)\b[\s.:-]+(?P<description>.*\S)\s*$", re.IGNORECASE)
HEAT_HEADER = re.compile(
    r"^\s*Heat\s+(?P<heat>\d{1,3})(?:\s+of\s+\d{1,3})?\s*(?P<round>Prelims|Preliminaries|Finals|Timed Finals|Semi-?Finals|Swim-?off)?",
    re.IGNORECASE,
)
SESSION_HEADER = re.compile(r"^\s*Session:?\s*(?P<number>\d{1,2})\b[\s:-]*(?P<name>.*\S)?\s*$", re.IGNORECASE)
INDIVIDUAL_LINE = re.compile(
    rf"^\s*(?P<lane>\d{{1,2}})\s+(?P<last>[A-Za-z][A-Za-z'’.\- ]*?),\s*(?P<first>[A-Za-z][A-Za-z'’.\- ]*?)"
    rf"\s+(?P<age>\d{{1,2}})\s+(?P<team>\S.*?)\s*(?P<seed>{_SEED})?\s*$"
)
RELAY_LINE = re.compile(
    rf"^\s*(?P<lane>\d{{1,2}})\s+(?P<team>\S.*?)\s+['\"]?(?P<letter>[A-Z])['\"]?\s*(?P<seed>{_SEED})?\s*$"
)
RELAY_SWIMMER = re.compile(r"(?P<leg>[1-8])\)\s*(?P<last>[A-Za-z][A-Za-z'’.\- ]*?),\s*(?P<first>[A-Za-z][A-Za-z'’.\- ]*?)\s+[WMBG]?(?P<age>\d{1,2})\b")
# Lines that are page furniture, never data.
_IGNORED_LINE = re.compile(r"HY-TEK|Meet Manager|Page \d+|Lane\s+Name|Name\s+Age\s+Team|Team\s+Relay", re.IGNORECASE)
# Two-column pages: a header starting this far from the left marks the second column.
MIN_SECOND_COLUMN_OFFSET = 20
COLUMN_MARKER = re.compile(r"(?:Event\s+\d|Heat\s+\d)", re.IGNORECASE)
RELAY_TEAM_FORMAT = "{club}-{letter}"
# A trailing middle initial ("Jane M") is dropped from first names.
MIDDLE_INITIAL = re.compile(r"\s+[A-Z]\.?$")
RELAY_TEAM_NAME_MAX_WORDS = 6
UNREAD_LINES_WARNING = "{count} lines inside events were not understood (first: {example!r})"


def split_columns(page_lines: list[str]) -> list[str]:
    """Return a page's lines in reading order, splitting two-column layouts.

    ``pdftotext -layout`` keeps columns side by side. If headers ("Event 12",
    "Heat 1 of 3") start well to the right on several lines, the page has two
    columns: every line is cut at that position and the left column is read first.
    """
    right_starts = [
        match.start()
        for line in page_lines
        for match in COLUMN_MARKER.finditer(line)
        if match.start() >= MIN_SECOND_COLUMN_OFFSET
    ]
    if len(right_starts) < 2:
        return page_lines
    split_at = min(right_starts)
    left = [line[:split_at].rstrip() for line in page_lines]
    right = [line[split_at:].rstrip() for line in page_lines]
    return left + right


def parse_report_lines(lines: Iterable[str], meet_name: str = "") -> MeetProgram:
    """Read events, heats, entries and sessions from report text lines.

    Args:
        lines: The report's text, one printed line per item, in reading order.
        meet_name: The meet name if the caller already knows it.

    Returns:
        The meet program. Events are listed once even if a report repeats their
        header on a new page.
    """
    program = MeetProgram(meet_name=meet_name)
    events: dict[str, ProgramEvent] = {}
    sessions: dict[str, ProgramSession] = {}
    current_event: ProgramEvent | None = None
    current_heat = ""
    current_round: str | None = None
    current_session: ProgramSession | None = None
    last_relay: ProgramEntry | None = None
    unread: list[str] = []
    for raw_line in lines:
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if (session := SESSION_HEADER.match(line)) is not None:
            number = session.group("number")
            current_session = sessions.setdefault(number, ProgramSession(number=number, name=(session.group("name") or "").strip()))
            continue
        if (header := EVENT_HEADER.match(line)) is not None and _looks_like_event(header.group("description")):
            number = normalize_event_number(header.group("number"))
            current_event = events.get(number)
            if current_event is None:
                current_event = ProgramEvent.from_description(number, header.group("description"))
                if current_session is not None:
                    current_event.session = current_session.number
                    current_session.event_numbers.append(number)
                events[number] = current_event
            current_heat, current_round, last_relay = "", None, None
            continue
        if (heat := HEAT_HEADER.match(line)) is not None:
            current_heat = str(int(heat.group("heat")))
            current_round = (heat.group("round") or "").title() or None
            if current_event is not None and current_round and not current_event.round:
                current_event.round = current_round
            continue
        if _IGNORED_LINE.search(line) or current_event is None:
            if not program.meet_name and current_event is None and not _IGNORED_LINE.search(line) and len(line.split()) >= 2:
                program.meet_name = " ".join(line.split())
            continue
        if current_event.relay:
            swimmers = list(RELAY_SWIMMER.finditer(line))
            if swimmers and last_relay is not None:
                last_relay.relay_swimmers.extend(format_swimmer_name(item.group("first"), item.group("last")) for item in swimmers)
                continue
            if (relay := RELAY_LINE.match(line)) is not None and len(relay.group("team").split()) <= RELAY_TEAM_NAME_MAX_WORDS:
                club = club_code(relay.group("team"))
                last_relay = ProgramEntry(
                    event_number=current_event.number,
                    heat=current_heat,
                    lane=str(int(relay.group("lane"))) if current_heat else "",
                    swimmer=RELAY_TEAM_FORMAT.format(club=club, letter=relay.group("letter")),
                    club=club,
                    seed_time=(relay.group("seed") or "").replace(" ", ""),
                    relay=True,
                    round=current_round,
                )
                program.entries.append(last_relay)
                continue
        elif (entry := INDIVIDUAL_LINE.match(line)) is not None:
            program.entries.append(
                ProgramEntry(
                    event_number=current_event.number,
                    heat=current_heat,
                    lane=str(int(entry.group("lane"))) if current_heat else "",
                    swimmer=format_swimmer_name(MIDDLE_INITIAL.sub("", entry.group("first")), entry.group("last")),
                    club=club_code(entry.group("team")),
                    age=int(entry.group("age")),
                    seed_time=(entry.group("seed") or "").replace(" ", ""),
                    round=current_round,
                )
            )
            continue
        unread.append(line.strip())
    program.events = list(events.values())
    program.sessions = list(sessions.values())
    if unread:
        program.warnings.append(UNREAD_LINES_WARNING.format(count=len(unread), example=unread[0][:80]))
    return program


def parse_report_text(text: str, meet_name: str = "") -> MeetProgram:
    """Read a whole report given as text (pages separated by form feeds)."""
    lines: list[str] = []
    for page in text.split("\f"):
        lines.extend(split_columns(page.splitlines()))
    return parse_report_lines(lines, meet_name)


def _looks_like_event(description: str) -> bool:
    """True if an "Event N ..." line really is an event header (it names a distance or stroke)."""
    event = ProgramEvent.from_description("0", description)
    return event.distance is not None or event.stroke is not None
