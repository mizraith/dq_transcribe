"""Read a meet sheet (the meet announcement) to set up a new meet.

Meet sheets vary, but most follow the same plan (Pacific Swimming's template and
its relatives), and announce what the app needs:

* the **meet name**: the title. Often line 1; on the standard template line 1 is
  the host club and line 2 the meet ("PALO ALTO STANFORD AQUATICS" / "PACIFIC
  SWIMMING SHORT COURSE C/B/A+ MEET"), which is read as "meet (host)";
* the **dates**: "Friday, October 16, 2026", "February 7-8, 2026",
  "May 30th–June 1st, 2025", "Saturday April 25 and Sunday April 26, 2026";
* the **sessions**, from the TIME paragraph: "Meet will begin at 9:00 AM each day
  with warm-ups from 7:30 to 8:50 AM", "FRIDAY SESSION: Meet begins at 4:30pm;
  Warm-Up is from 3:30 to 4:20", "Competition shall begin at 5:00 p.m. on Friday
  30 May", "not before 12:00 PM";
* the **events**: numbered, often with girls' and boys' numbers on either side,
  sometimes two pairs to a line or qualifying times between ("1  2:24.79  200 IM
  2:12.29  2"), or a table in a Word file;
* the **officials** (MEET PERSONNEL / OFFICIALS block): "Meet Referee: Name",
  "Head Starter: Name", "Admin Official / Admin Ref: Name", "Meet Director: Name",
  several per line.

Whatever is found becomes the meet: name and first day, the officials (in their
roster roles), and a meet program of events and sessions (no swimmers yet: those
come with the heat sheet). Whatever is not found is listed, so the admin knows
what to fill in. The reader is a set of patterns: a sheet it does not understand
still gives a meet with a name and date to edit.
"""

from __future__ import annotations

import html
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from dq_transcribe import constants
from dq_transcribe.meet_files.errors import MeetFileError
from dq_transcribe.meet_files.html_report import html_text
from dq_transcribe.meet_files.model import MeetProgram, ProgramEvent, ProgramSession, normalize_event_number
from dq_transcribe.meet_files.pdf_report import pdf_text

MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december")
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_MONTH = r"(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec)\.?"
_ORDINAL = r"(?:st|nd|rd|th)?"
# "October 16, 2026", "June 6-8, 2025", "May 30th–June 1st, 2025", "April 25 and Sunday April 26, 2026"
DATE_PATTERN = re.compile(
    rf"{_MONTH}\s+(\d{{1,2}}){_ORDINAL}"
    rf"(?:\s*(?:-|–|—|&|and|to|through)\s*(?:(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day,?\s+)?(?:{_MONTH}\s+)?(\d{{1,2}}){_ORDINAL})?"
    rf",?\s+(\d{{4}})",
    re.IGNORECASE,
)
NUMERIC_DATE_PATTERN = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
TIME = r"(\d{1,2}(?::\d{2})?)\s*([ap]\.?\s?m\.?)?"
TIME_RANGE = rf"{TIME}\s*(?:-|–|—|to|until)\s*{TIME}"
WARMUP_PATTERN = re.compile(rf"warm[\s-]?ups?\b[^.;\n]*?{TIME_RANGE}", re.IGNORECASE)
WARMUP_START_PATTERN = re.compile(rf"warm[\s-]?ups?\s+(?:will\s+)?(?:start|begin)s?\s+(?:at\s+)?{TIME}", re.IGNORECASE)
# "Meet will begin at 9:00 AM", "Competition shall begin at 5:00 p.m.", "Meet starts at 9:00AM", "Session Start: 9:00 AM"
_NOT_A_DURATION = r"(?!\s*(?:hours?|hrs?|minutes?|mins?)\b)"
START_PATTERN = re.compile(
    rf"(?:meet|competition|session|racing|events?)\s+(?:will\s+|shall\s+)?(?:start|begin)s?\s*(?:at|:)?\s+{TIME}{_NOT_A_DURATION}"
    rf"|not\s+before\s+{TIME}{_NOT_A_DURATION}",
    re.IGNORECASE,
)
# A start time written without am/pm before this hour is afternoon ("not before 1").
EARLIEST_MORNING_HOUR = 6
DAYS_NEAR_START_CHARS = 60
# Sentences and semicolon clauses of the TIME paragraph ("a.m." does not end one).
CLAUSE_BREAK = re.compile(r"(?<![ap]\.m\.)(?<=[.;])\s+", re.IGNORECASE)
TIME_SECTION_START = re.compile(r"^\s*TIMES?\s*:", re.IGNORECASE)
SECTION_HEADING = re.compile(r"^\s*[A-Z][A-Z /&'-]{2,}:")
EVERY_DAY = re.compile(r"\b(each|every|both)\s+(day|days|morning)\b|\bdaily\b", re.IGNORECASE)
SESSION_LINE = re.compile(r"^\s*Session\s*(\d{1,2})\b(.*)$", re.IGNORECASE)
EVENTS_HEADER = re.compile(r"\b(Girls|Women|Female)\b.*\bEvents?\b.*\b(Boys|Men|Male)\b", re.IGNORECASE)
GENDERS_LINE = re.compile(r"^\s*(Girls|Women|Female)\s+(Boys|Men|Male)\s*$", re.IGNORECASE)
# An age-group cell before the event ("10&U", "11-12", "13&O", "Open").
AGE_TOKEN = re.compile(
    r"^(\d{1,2})\s*(?:&|and|/|-)?\s*(U|UN|Under|O|Over|Up)$|^(\d{1,2})\s*[-/]\s*(\d{1,2})$|^Open$", re.IGNORECASE
)
AGE_WORDS = {"u": "Under", "un": "Under", "under": "Under", "o": "Over", "over": "Over", "up": "Over"}
# Race distances: a lone "400" next to "400 IM" in a time-standards table is not event 400.
STANDARD_DISTANCES = frozenset({25, 50, 100, 200, 400, 500, 800, 1000, 1500, 1650})
EVENT_NEIGHBOR_DISTANCE = 3
MIXED_WORD = re.compile(r"\b(mixed|combined)\b", re.IGNORECASE)
MOSTLY_GENDERED_SHARE = 0.8
TWO_COLUMN_EVENT = re.compile(r"^\s*#?(\d{1,3}[A-Za-z]?)[.)]?\s+(.+?)\s+#?(\d{1,3}[A-Za-z]?)\s*$")
ONE_COLUMN_EVENT = re.compile(r"^\s*(?:Event\s*|#)?(\d{1,3}[A-Za-z]?)[.):]?\s+(.+?)\s*$", re.IGNORECASE)
EVENT_NUMBER_TOKEN = re.compile(r"^#?(\d{1,3}[A-Za-z]?)[.)]?$")
# Qualifying-time columns between event numbers ("2:24.79", "27.69", "---", "NT").
TIME_TOKEN = re.compile(r"^(?:\d{1,2}:)?\d{1,2}\.\d{2}\*?$|^-{2,}$|^NT$", re.IGNORECASE)
CELL_GAP = re.compile(r"\s{2,}|\t")
COURSE_PATTERN = re.compile(r"\b(25|50)[\s-]*(yard|yd|meter|metre|m)\b", re.IGNORECASE)
LOCATION_PATTERN = re.compile(r"^\s*(?:LOCATION|FACILITY|SITE|VENUE)\s*:\s*(.+)$", re.IGNORECASE)
HOSTED_BY = re.compile(r"^\s*hosted\s+by\b", re.IGNORECASE)
MEET_WORDS = re.compile(
    r"\b(meet|invitational|invite|classic|championships?|open|block\s+party|splash|festival|dual|trials|cup|games|"
    r"showdown|challenge|series|qualifier|sectionals?|junior|senior)\b",
    re.IGNORECASE,
)
# One person's name in an officials block: capitalized words separated by single
# spaces (two or more spaces end it, so the next title on the line is not swallowed).
_NAME = r"([A-Z][A-Za-z'’.-]*(?: (?:\"[A-Za-z]+\" )?[A-Z][A-Za-z'’.-]*){1,3})"
OFFICIAL_TITLES = (
    # (pattern for the title as written, roster role or None if the role is not on the roster)
    (r"Meet\s+Director", None),
    (r"Meet\s+Marshal", None),
    (r"Meet\s+Referee", "Meet Referee"),
    (r"Deck\s+Referee", "Deck Referee"),
    (r"Admin(?:istrative)?\.?\s+(?:Official|Referee|Ref)\b", "Admin Official"),
    (r"(?:Head\s+)?Starter", "Starter"),
    (r"(?<!Meet )(?<!Deck )(?<!Admin )Referee", "Meet Referee"),
)
TITLE_WORDS = frozenset({"head", "meet", "admin", "deck", "starter", "referee", "marshal", "director", "official", "ref"})
MIN_NAME_WORDS = 2
TITLE_LINES = 4  # the title is in the first few lines
TITLE_MAX_CHARS = 100
CLOCK_24_HOUR = "%H:%M"
PDF_SIGNATURE = b"%PDF"
HTML_EXTENSIONS = (".htm", ".html")
HTML_MARKER = "<html"
HTML_SNIFF_CHARS = 2000
TEXT_ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")
INVISIBLE_CHARACTERS = re.compile("[​‌‍﻿]")
NOT_FOUND = {
    "date": "the date (set the first day by hand)",
    "sessions": "session times",
    "events": "the events (load the heat sheet or Meet Manager file later)",
    "officials": "officials (none are named on the sheet)",
}
TWELVE_HOURS = 12
NOON_HOUR = 12
DOCX_DOCUMENT = "word/document.xml"
DOCX_CELL_GAP = "    "


@dataclass
class MeetSheet:
    """What was read from a meet sheet."""

    name: str = ""
    dates: list[date] = field(default_factory=list)
    course: str | None = None
    location: str = ""
    sessions: list[ProgramSession] = field(default_factory=list)
    events: list[ProgramEvent] = field(default_factory=list)
    officials: list[dict[str, str]] = field(default_factory=list)  # {"name", "role", "title"}; role None if not a roster role
    missing: list[str] = field(default_factory=list)

    @property
    def start_date(self) -> date | None:
        """The meet's first day."""
        return min(self.dates) if self.dates else None

    def program(self) -> MeetProgram:
        """The events and sessions as a meet program (no swimmers yet)."""
        return MeetProgram(meet_name=self.name, events=self.events, sessions=self.sessions)

    def summary(self) -> dict:
        """What was found and what is missing, for the page."""
        return {
            "name": self.name,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "days": len(self.dates),
            "course": self.course,
            "location": self.location,
            "sessions": [{"name": session.name, "day": session.day, "start_time": session.start_time} for session in self.sessions],
            "events": len(self.events),
            "officials": self.officials,
            "missing": self.missing,
        }


# --- Times and dates -------------------------------------------------------------


def _meridiem(text: str | None) -> str:
    """"p.m." -> "pm"."""
    return re.sub(r"[.\s]", "", text or "").lower()


def _clock(hour_minute: str, meridiem: str | None, default_meridiem: str | None = None) -> str:
    """"4:45", "pm" -> "16:45" (a missing am/pm is taken from ``default_meridiem``)."""
    hour_text, _, minute_text = hour_minute.partition(":")
    hour, minute = int(hour_text), int(minute_text or 0)
    meridiem = _meridiem(meridiem) or _meridiem(default_meridiem)
    if meridiem == "pm" and hour < NOON_HOUR:
        hour += TWELVE_HOURS
    if meridiem == "am" and hour == NOON_HOUR:
        hour = 0
    return f"{hour:02d}:{minute:02d}"


def _twelve_hour(clock: str) -> str:
    """"16:45" -> "4:45 PM"."""
    return datetime.strptime(clock, CLOCK_24_HOUR).strftime(constants.CLOCK_FORMAT_12_HOUR).lstrip("0")


def _month_number(name: str) -> int:
    """"Oct" or "October" -> 10."""
    return next(index for index, month in enumerate(MONTHS, start=1) if month.startswith(name.lower()[:3]))


def _dates(text: str) -> list[date]:
    """Every date mentioned, in order of appearance (a range adds each day)."""
    found: list[tuple[int, date]] = []
    for match in DATE_PATTERN.finditer(text):
        first_month, first_day, second_month, last_day, year = match.groups()
        try:
            first = date(int(year), _month_number(first_month), int(first_day))
            last = date(int(year), _month_number(second_month or first_month), int(last_day)) if last_day else first
        except ValueError:
            continue
        if not timedelta(0) <= last - first <= timedelta(days=constants.MEET_SHEET_MAX_MEET_DAYS):
            last = first
        found.extend((match.start(), first + timedelta(days=offset)) for offset in range((last - first).days + 1))
    for match in NUMERIC_DATE_PATTERN.finditer(text):
        try:
            found.append((match.start(), date(int(match.group(3)), int(match.group(1)), int(match.group(2)))))
        except ValueError:
            continue
    found.sort(key=lambda item: item[0])
    return [day for _, day in found]


def _meet_days(text: str) -> list[date]:
    """The meet's days: the first date mentioned (under the title) and the days next to it.

    Later dates on a sheet are usually deadlines ("entries due October 14"), so only
    dates within a few days after the first one count as meet days.
    """
    all_dates = _dates(text)
    if not all_dates:
        return []
    first = all_dates[0]
    limit = timedelta(days=constants.MEET_SHEET_MAX_MEET_DAYS - 1)
    return sorted({day for day in all_dates if timedelta(0) <= day - first <= limit})


# --- Title, officials, location -----------------------------------------------------


def _title(lines: list[str]) -> str:
    """The meet name: the first line that names a meet; a host club line above it is kept in brackets."""
    candidates = []
    for line in lines:
        text = " ".join(line.split())
        if not text:
            continue
        if _dates(text) or len(candidates) >= TITLE_LINES:
            break
        candidates.append(text)
    if not candidates:
        return ""
    first = candidates[0]
    if MEET_WORDS.search(first):
        return first[:TITLE_MAX_CHARS]
    meet_line = next((line for line in candidates[1:] if MEET_WORDS.search(line) and not HOSTED_BY.match(line)), None)
    if meet_line:
        return f"{meet_line} ({first})"[:TITLE_MAX_CHARS]
    return first[:TITLE_MAX_CHARS]


def _officials(text: str) -> list[dict[str, str]]:
    """Named officials ("Meet Referee: Pat Lee"), each with its roster role (None for e.g. Meet Director).

    "Meet Referee: Ann Lee/Bob Kim" names two people.
    """
    officials = []
    seen: set[str] = set()
    for title_pattern, role in OFFICIAL_TITLES:
        for match in re.finditer(rf"\b({title_pattern})[ \t]*[:\-–][ \t]*{_NAME}((?:/{_NAME[1:-1]})*)", text):
            names = [match.group(2), *[name for name in match.group(3).split("/") if name]]
            for name in (_cut_at_title_word(" ".join(name.split())) for name in names):
                if len(name.split()) < MIN_NAME_WORDS:
                    continue
                if name in seen:
                    continue  # already found under a more specific title
                seen.add(name)
                officials.append({"name": name, "role": role, "title": " ".join(match.group(1).split())})
    return officials


def _cut_at_title_word(name: str) -> str:
    """"Lucille Glassman Head Starter" -> "Lucille Glassman" (the next title on the line)."""
    words = name.split()
    for index, word in enumerate(words):
        if word.lower() in TITLE_WORDS:
            return " ".join(words[:index])
    return name


def _location(lines: list[str]) -> str:
    """The pool: the LOCATION (or FACILITY) line, without directions."""
    for line in lines:
        match = LOCATION_PATTERN.match(line)
        if match:
            place = re.split(r":\s|\.\s", " ".join(match.group(1).split()), maxsplit=1)[0]
            return place[:TITLE_MAX_CHARS]
    return ""


# --- Sessions -----------------------------------------------------------------------


def _time_section(lines: list[str]) -> str:
    """The TIME paragraph (up to the next HEADING:), as one string; the whole text if there is none."""
    for index, line in enumerate(lines):
        if TIME_SECTION_START.match(line):
            section = [line]
            for following in lines[index + 1:]:
                if SECTION_HEADING.match(following):
                    break
                section.append(following)
            return " ".join(" ".join(section).split())
    return ""


def _days_named(text: str, meet_days: list[date]) -> list[date]:
    """Meet days named in a clause by weekday ("Friday", "SATURDAY/SUNDAY")."""
    lowered = text.lower()
    return [day for day in meet_days if WEEKDAYS[day.weekday()] in lowered]


def _sessions(lines: list[str], text: str, meet_days: list[date]) -> list[ProgramSession]:
    """Sessions with their day and start time.

    Each clause of the TIME paragraph that gives a start ("begin at 9:00 AM",
    "not before 12:00 PM") makes a session on the days it names ("Friday",
    "SATURDAY/SUNDAY", "on Saturday 31 May"), on every day ("each day", "both
    days"), or else on the first day. "Session N" lines are used when the sheet has them.
    """
    sessions: list[tuple[str, str, str]] = []  # (day, start, warm-up)
    numbered = [SESSION_LINE.match(line) for line in lines]
    for match in (item for item in numbered if item):
        rest = match.group(2)
        start = START_PATTERN.search(rest) or re.search(rf"start\w*\s*(?:at\s*)?:?\s*{TIME}", rest, re.IGNORECASE)
        days = _days_named(rest, meet_days)
        if start and days:
            sessions.extend((day.isoformat(), _start_clock(start), "") for day in days)
    if not sessions:
        paragraph = _time_section(lines) or text
        clauses = [clause for clause in CLAUSE_BREAK.split(paragraph) if clause.strip()]
        every_day = bool(_time_section(lines) and EVERY_DAY.search(paragraph))
        carried_days: list[date] = []
        last_added: list[int] = []  # the sessions the previous clause added
        carried_warmup: re.Match | None = None  # "warm-ups from 4:00-4:45 pm. The meet will start at 4:45pm."
        for clause in clauses:
            starts = list(START_PATTERN.finditer(clause))
            if not starts and _days_named(clause, meet_days):
                carried_days = _days_named(clause, meet_days)
            if not starts:
                warmup_only = WARMUP_PATTERN.search(clause)
                if warmup_only and last_added and not any(sessions[index][2] for index in last_added):
                    # "Meet begins at 4:30pm; Warm-Up is from 3:30 to 4:20": belongs to the start just before.
                    for index in last_added:
                        day, start_clock, _ = sessions[index]
                        sessions[index] = (day, start_clock, _clock(warmup_only.group(1), warmup_only.group(2),
                                                                     warmup_only.group(4) or _meridiem_of(start_clock)))
                    last_added = []
                else:
                    carried_warmup = warmup_only or carried_warmup
                continue
            last_added = []
            for start in starts:
                # The days this start is for are named near it ("... at 9:00 a.m. on Saturday 31 May and Sunday 1 June").
                near = clause[: start.end() + DAYS_NEAR_START_CHARS]
                named_near = _days_named(near, meet_days)
                if named_near:
                    carried_days = named_near
                if EVERY_DAY.search(near) or not meet_days:
                    days = meet_days
                else:
                    days = named_near or carried_days or (meet_days if every_day else meet_days[:1])
                warmup = WARMUP_PATTERN.search(clause) or carried_warmup
                carried_warmup = None
                start_clock = _start_clock(start)
                warmup_clock = _warmup_clock(warmup, start) if warmup else ""
                warmup_start = None if warmup else WARMUP_START_PATTERN.search(clause)
                if warmup_start:  # "Warm-ups start at 7:30AM and the Meet starts at 9:00AM"
                    warmup_clock = _clock(warmup_start.group(1), warmup_start.group(2), _meridiem_of(start_clock))
                for day in days or [None]:
                    last_added.append(len(sessions))
                    sessions.append((day.isoformat() if day else "", start_clock, warmup_clock))
    first_seen: dict[tuple[str, str], tuple[str, str, str]] = {}
    for item in sessions:
        first_seen.setdefault((item[0], item[1]), item)  # the same start said twice: keep the first
    unique = sorted(first_seen.values(), key=lambda item: (item[0], item[1]))
    result = []
    for number, (day, start, warmup) in enumerate(unique, start=1):
        weekday = datetime.fromisoformat(day).strftime("%A") if day else "Session"
        name = f"{weekday} {_twelve_hour(start)}" + (f" (warm-up {_twelve_hour(warmup)})" if warmup else "")
        result.append(ProgramSession(number=str(number), name=name, day=day or None, start_time=start))
    return result


def _meridiem_of(clock: str) -> str:
    """"16:30" -> "pm" (for a warm-up written without am/pm after that start)."""
    return "pm" if int(clock.split(":")[0]) >= NOON_HOUR else "am"


def _start_clock(match: re.Match) -> str:
    """The 24-hour start time from a START_PATTERN match (either alternative)."""
    groups = [group for group in match.groups()]
    hour_minute, meridiem = (groups[0], groups[1]) if groups[0] else (groups[2], groups[3])
    if not meridiem and int(hour_minute.split(":")[0]) < EARLIEST_MORNING_HOUR:
        meridiem = "pm"
    return _clock(hour_minute, meridiem)


def _warmup_clock(warmup: re.Match, start: re.Match) -> str:
    """When warm-up begins: am/pm from the warm-up's own range, else from the start time."""
    start_groups = start.groups()
    start_meridiem = start_groups[1] if start_groups[0] else start_groups[3]
    return _clock(warmup.group(1), warmup.group(2), warmup.group(4) or start_meridiem)


# --- Events -------------------------------------------------------------------------


def _is_event(description: str) -> bool:
    """True if the text names a distance and a stroke ("Open 100 free", "200m Free")."""
    event = ProgramEvent.from_description("0", description)
    return event.stroke is not None and event.distance is not None


def _with_gender(description: str, gender: str | None) -> str:
    """Add the column's gender ("Girls") unless the description already has one."""
    if gender and not re.search(r"\b(girls|boys|women|men|mixed|combined)\b", description, re.IGNORECASE):
        return f"{gender} {description}"
    return description


def _events_in_cells(cells: list[str], left_gender: str | None, right_gender: str | None) -> list[tuple[str, str]]:
    """Events in one line split into cells: "1 | 9 & Over 200 Free | 2 | 21 | 9 & Over 200 IM | 22".

    A description between two numbers is a girls/boys pair; qualifying times
    between them are skipped.
    """
    cells = _merge_age_cells([cell for cell in cells if cell and not TIME_TOKEN.match(cell)])
    found = []
    index = 0
    while index < len(cells):
        number = EVENT_NUMBER_TOKEN.match(cells[index])
        if number and index + 1 < len(cells) and _is_event(cells[index + 1]):
            description = cells[index + 1]
            right = EVENT_NUMBER_TOKEN.match(cells[index + 2]) if index + 2 < len(cells) else None
            if right and not MIXED_WORD.search(description):  # a mixed event has one number
                found.append((number.group(1), _with_gender(description, left_gender)))
                found.append((right.group(1), _with_gender(description, right_gender)))
                index += 3
                continue
            found.append((number.group(1), description))
            index += 2
            continue
        index += 1
    return found


def _merge_age_cells(cells: list[str]) -> list[str]:
    """Join an age-group cell to the event after it: ["1", "10&U", "200 IM", "2"] -> ["1", "10 & Under 200 IM", "2"]."""
    merged: list[str] = []
    index = 0
    while index < len(cells):
        age = AGE_TOKEN.match(cells[index])
        if age and index + 1 < len(cells) and _is_event(cells[index + 1]):
            if age.group(1):
                label = f"{age.group(1)} & {AGE_WORDS[age.group(2).lower()]}"
            elif age.group(3):
                label = f"{age.group(3)}-{age.group(4)}"  # "11/12" -> "11-12"
            else:
                label = cells[index]
            merged.append(f"{label} {cells[index + 1]}")
            index += 2
            continue
        merged.append(cells[index])
        index += 1
    return merged


def _number_is_distance(event: ProgramEvent) -> bool:
    """True if an event's number is the same as its distance (50 for a 50 Free): a hint it is not an event."""
    digits = re.sub(r"\D", "", event.number)
    return bool(digits) and event.distance == int(digits)


def _drop_stray_numbers(events: dict[str, ProgramEvent]) -> None:
    """Remove "events" that are really a time-standards table: a number equal to a race
    distance ("400", "50") with no other event number near it."""
    numbers = {key: int(re.sub(r"\D", "", key) or 0) for key in events}
    with_gender = sum(1 for event in events.values() if event.gender)
    mostly_gendered = with_gender >= len(events) * MOSTLY_GENDERED_SHARE
    for key, number in list(numbers.items()):
        if number not in STANDARD_DISTANCES:
            continue
        nearest = min((abs(value - number) for other, value in numbers.items() if other != key), default=None)
        same_as_distance = events[key].distance == number
        if nearest is None or nearest > EVENT_NEIGHBOR_DISTANCE or (same_as_distance and (nearest > 1 or (mostly_gendered and not events[key].gender))):
            del events[key]


def _events(lines: list[str], course: str | None) -> list[ProgramEvent]:
    """Numbered events, in any of the usual layouts."""
    events: dict[str, ProgramEvent] = {}
    left_gender = right_gender = None

    def add(number: str, description: str) -> None:
        key = normalize_event_number(number)
        if len(description) >= constants.MEET_SHEET_MAX_EVENT_CHARS:
            return
        event = ProgramEvent.from_description(key, description, course=course)
        existing = events.get(key)
        # First one wins, except over a lookalike from a distance table ("50" next to "50 Free").
        if existing is None or (_number_is_distance(existing) and not _number_is_distance(event)):
            events[key] = event

    for line in lines:
        header = EVENTS_HEADER.search(line) or GENDERS_LINE.match(line)
        if header:
            left_gender, right_gender = header.group(1).title(), header.group(2).title()
            continue
        cells = [cell.strip() for cell in CELL_GAP.split(line.strip()) if cell.strip()]
        if len(cells) >= 2:
            pairs = _events_in_cells(cells, left_gender, right_gender)
            if pairs:
                for number, description in pairs:
                    add(number, description)
                continue
        two = TWO_COLUMN_EVENT.match(line)
        if two and _is_event(two.group(2)):
            left, description, right = two.groups()
            add(left, _with_gender(description, left_gender))
            add(right, _with_gender(description, right_gender))
            continue
        one = ONE_COLUMN_EVENT.match(line)
        if one and _is_event(one.group(2)):
            add(one.group(1), one.group(2))
    _drop_stray_numbers(events)
    return sorted(events.values(), key=lambda event: (int(re.sub(r"\D", "", event.number) or 0), event.number))


# --- Reading ------------------------------------------------------------------------


def read_meet_sheet_text(text: str) -> MeetSheet:
    """Read a meet sheet given as text."""
    text = INVISIBLE_CHARACTERS.sub("", text.replace("\r", ""))
    lines = [line.rstrip() for line in text.splitlines()]
    sheet = MeetSheet()
    sheet.name = _title(lines)
    sheet.dates = _meet_days(text)
    course = COURSE_PATTERN.search(text)
    if course:
        sheet.course = "Yard" if course.group(2).lower().startswith("y") else "Meter"
    sheet.location = _location(lines)
    sheet.events = _events(lines, sheet.course)
    sheet.sessions = _sessions(lines, text, sheet.dates)
    if len(sheet.sessions) == 1:
        sheet.sessions[0].event_numbers = [event.number for event in sheet.events]
        for event in sheet.events:
            event.session = sheet.sessions[0].number
    sheet.officials = _officials(text)
    for key, found in (("date", sheet.dates), ("sessions", sheet.sessions), ("events", sheet.events), ("officials", sheet.officials)):
        if not found:
            sheet.missing.append(NOT_FOUND[key])
    return sheet


def _strip_tags(xml: str) -> str:
    """The text of some Word XML: its text runs joined as written (their own spaces kept), tabs kept."""
    parts = []
    for text, tab_or_break in re.findall(r"<w:t(?:\s[^>]*)?>(.*?)</w:t>|<w:(tab|br)/>", xml, flags=re.DOTALL):
        parts.append(html.unescape(text) if text else ("\t" if tab_or_break == "tab" else " "))
    return "".join(parts)


def _docx_text(path: Path) -> str:
    """The text of a Word document: paragraphs as lines, table rows as lines of cells."""
    with zipfile.ZipFile(path) as archive:
        xml = archive.read(DOCX_DOCUMENT).decode("utf-8", errors="replace")

    def table_text(match: re.Match) -> str:
        rows = []
        for row in re.findall(r"<w:tr\b.*?</w:tr>", match.group(0), flags=re.DOTALL):
            cells = [" ".join(_strip_tags(cell).split()) for cell in re.findall(r"<w:tc\b.*?</w:tc>", row, flags=re.DOTALL)]
            rows.append(DOCX_CELL_GAP.join(cells))
        # Each row becomes a paragraph holding one text run (read like any other paragraph below).
        return "".join(f"<w:p><w:r><w:t>{html.escape(row)}</w:t></w:r></w:p>" for row in rows)

    xml = re.sub(r"<w:tbl>.*?</w:tbl>", table_text, xml, flags=re.DOTALL)
    paragraphs = re.findall(r"<w:p\b[^>]*>(.*?)</w:p>|<w:p>(.*?)</w:p>", xml, flags=re.DOTALL)
    return "\n".join(_strip_tags(first or second) for first, second in paragraphs)


def _has_word_document(path: Path) -> bool:
    """True if a zip file is a Word document."""
    try:
        with zipfile.ZipFile(path) as archive:
            return DOCX_DOCUMENT in archive.namelist()
    except zipfile.BadZipFile:
        return False


def _decode(raw: bytes) -> str:
    """Text from bytes: UTF-8 if valid, else Windows' usual encoding."""
    for encoding in TEXT_ENCODINGS:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode(TEXT_ENCODINGS[-1], errors="replace")


def read_meet_sheet_file(path: Path, original_name: str = "") -> MeetSheet:
    """Read a meet sheet file: PDF, Word (.docx), HTML or plain text.

    Raises:
        MeetFileError: If the file has no readable text.
    """
    name = (original_name or path.name).lower()
    raw = path.read_bytes()
    if raw.startswith(PDF_SIGNATURE):
        text = pdf_text(path)
    elif zipfile.is_zipfile(path) and _has_word_document(path):
        text = _docx_text(path)
    else:
        decoded = _decode(raw)
        is_html = name.endswith(HTML_EXTENSIONS) or HTML_MARKER in decoded[:HTML_SNIFF_CHARS].lower()
        text = html_text(decoded) if is_html else decoded
    if not text.strip():
        raise MeetFileError("The meet sheet has no text this app can read.")
    return read_meet_sheet_text(text)


def download_address(url: str) -> str:
    """The address to download a shared document as a file.

    Google Docs links (…/document/d/<id>/edit, /mobilebasic, …) become their plain
    text export; Google Drive file links become a direct download. Other addresses
    are used as they are.
    """
    google_doc = re.search(r"docs\.google\.com/document/(?:u/\d+/)?d/([A-Za-z0-9_-]+)", url)
    if google_doc:
        return f"https://docs.google.com/document/d/{google_doc.group(1)}/export?format=txt"
    drive_file = re.search(r"drive\.google\.com/(?:file/d/|open\?id=)([A-Za-z0-9_-]+)", url)
    if drive_file:
        return f"https://drive.google.com/uc?export=download&id={drive_file.group(1)}"
    return url


def today() -> date:
    """Today's date on this device (for a sheet without a date)."""
    return datetime.now().date()
