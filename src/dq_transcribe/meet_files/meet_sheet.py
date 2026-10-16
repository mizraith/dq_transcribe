"""Read a meet sheet (the meet announcement) to set up a new meet.

Meet sheets vary in format, but they usually announce what the app needs:

* the **meet name**: the title, the first line;
* the **dates**: "Friday, October 16, 2026", "October 16-18, 2026", "10/16/2026";
* the **sessions**: warm-up and start times ("warm-ups from 4:00-4:45 pm ... start at
  4:45pm", or one "Session 2 ... Saturday ... warm-up 7:00 AM, start 8:00 AM" line
  per session);
* the **events**: numbered lines, often girls' and boys' numbers on either side
  ("1 Open 100 free 2" under a "Girls Events Boys" header), or "Event 12 Girls 10 &
  Under 50 Breaststroke";
* the **officials**: "Meet Referee: Name", "Admin Official: Name", "Head Starter:
  Name", "Meet Director: Name".

Whatever is found becomes the meet: name and first day, the officials (in their
roster roles), and a meet program of events and sessions (no swimmers yet: those
come with the heat sheet). Whatever is not found is listed, so the admin knows
what to fill in. The reader is a set of patterns, so a sheet it does not
understand still gives a meet with a name and date to edit.
"""

from __future__ import annotations

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
_MONTH = r"(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec)\.?"
DATE_PATTERN = re.compile(
    rf"(?:(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day,?\s+)?{_MONTH}\s+(\d{{1,2}})(?:\s*(?:-|–|&|and|to)\s*(\d{{1,2}}))?(?:st|nd|rd|th)?,?\s+(\d{{4}})",
    re.IGNORECASE,
)
NUMERIC_DATE_PATTERN = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
TIME = r"(\d{1,2}(?::\d{2})?)\s*([ap]\.?m\.?)?"
WARMUP_PATTERN = re.compile(rf"warm[\s-]?ups?\b[^.\n]*?{TIME}\s*(?:-|–|to|until)\s*{TIME}", re.IGNORECASE)
START_PATTERN = re.compile(rf"(?:meet|competition|session|racing|events?)\s+(?:will\s+)?(?:start|begin)s?\s+(?:at\s+)?{TIME}", re.IGNORECASE)
SESSION_LINE = re.compile(r"^\s*Session\s*(\d{1,2})\b(.*)$", re.IGNORECASE)
EVENTS_HEADER = re.compile(r"\b(Girls|Women|Female)\b.*\bEvents?\b.*\b(Boys|Men|Male)\b", re.IGNORECASE)
TWO_COLUMN_EVENT = re.compile(r"^\s*#?(\d{1,3}[A-Za-z]?)[.)]?\s+(.+?)\s+#?(\d{1,3}[A-Za-z]?)\s*$")
ONE_COLUMN_EVENT = re.compile(r"^\s*(?:Event\s*|#)?(\d{1,3}[A-Za-z]?)[.):]?\s+(.+?)\s*$", re.IGNORECASE)
COURSE_PATTERN = re.compile(r"\b(25|50)[\s-]*(yard|yd|meter|metre|m)\b", re.IGNORECASE)
LOCATION_PATTERN = re.compile(r"^\s*(?:LOCATION|FACILITY|SITE|VENUE)\s*:\s*(.+)$", re.IGNORECASE)
# "Meet Referee: Pat Lee" (also "Meet Referee - Pat Lee"). The name: 2 to 4 capitalized words.
_NAME = r"([A-Z][A-Za-z'’.-]+(?:[ \t]+(?:\"[A-Za-z]+\"[ \t]+)?[A-Z][A-Za-z'’.-]+){1,3})"  # one line only
OFFICIAL_TITLES = (
    # (pattern for the title as written, roster role or None if the role is not on the roster)
    (r"Meet\s+Director", None),
    (r"Meet\s+Referee", "Meet Referee"),
    (r"Deck\s+Referee", "Deck Referee"),
    (r"Admin(?:istrative)?\s+(?:Official|Referee)", "Admin Official"),
    (r"(?:Head\s+)?Starter", "Starter"),
    (r"Referee", "Meet Referee"),
)
TITLE_MAX_CHARS = 100
CLOCK_24_HOUR = "%H:%M"
PDF_SIGNATURE = b"%PDF"
HTML_EXTENSIONS = (".htm", ".html")
HTML_MARKER = "<html"
HTML_SNIFF_CHARS = 2000
TEXT_ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")
NOT_FOUND = {
    "date": "the date (set the first day by hand)",
    "sessions": "session times",
    "events": "the events (load the heat sheet or Meet Manager file later)",
    "officials": "officials (none are named on the sheet)",
}
TWELVE_HOURS = 12
NOON_HOUR = 12


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


def _clock(hour_minute: str, meridiem: str | None, default_meridiem: str | None = None) -> str:
    """"4:45", "pm" -> "16:45"."""
    hour_text, _, minute_text = hour_minute.partition(":")
    hour, minute = int(hour_text), int(minute_text or 0)
    meridiem = (meridiem or default_meridiem or "").lower().replace(".", "")
    if meridiem == "pm" and hour < NOON_HOUR:
        hour += TWELVE_HOURS
    if meridiem == "am" and hour == NOON_HOUR:
        hour = 0
    return f"{hour:02d}:{minute:02d}"


def _dates(text: str) -> list[date]:
    """Every meet date mentioned, in order of appearance (a range adds each day)."""
    found: list[tuple[int, date]] = []
    for match in DATE_PATTERN.finditer(text):
        month_name, first_day, last_day, year = match.groups()
        month = next(index for index, name in enumerate(MONTHS, start=1) if name.startswith(month_name.lower()[:3]))
        try:
            first = date(int(year), month, int(first_day))
            days = [first + timedelta(days=offset) for offset in range((int(last_day) - int(first_day) + 1) if last_day else 1)]
        except ValueError:
            continue
        found.extend((match.start(), day) for day in days)
    for match in NUMERIC_DATE_PATTERN.finditer(text):
        try:
            found.append((match.start(), date(int(match.group(3)), int(match.group(1)), int(match.group(2)))))
        except ValueError:
            continue
    found.sort()
    return [day for _, day in found]


def _meet_days(text: str) -> list[date]:
    """The meet's days: the first date mentioned (usually under the title) and the days next to it.

    Later dates on a sheet are usually deadlines ("entries due October 14"), so
    only dates within a few days of the first one count as meet days.
    """
    all_dates = _dates(text)
    if not all_dates:
        return []
    first = all_dates[0]
    days = sorted({day for day in all_dates if timedelta(0) <= day - first <= timedelta(days=constants.MEET_SHEET_MAX_MEET_DAYS - 1)})
    return days


def _events(lines: list[str], course: str | None) -> list[ProgramEvent]:
    """Numbered event lines, in one column or with girls' and boys' numbers on either side."""
    events: dict[str, ProgramEvent] = {}
    left_gender = right_gender = None
    for line in lines:
        header = EVENTS_HEADER.search(line)
        if header:
            left_gender, right_gender = header.group(1).title(), header.group(2).title()
            continue
        two = TWO_COLUMN_EVENT.match(line)
        if two and _is_event(two.group(2)):
            left, description, right = two.groups()
            for number, gender in ((left, left_gender), (right, right_gender)):
                text = f"{gender} {description}" if gender and not re.search(r"\b(girls|boys|women|men|mixed)\b", description, re.IGNORECASE) else description
                events.setdefault(normalize_event_number(number), ProgramEvent.from_description(number, text, course=course))
            continue
        one = ONE_COLUMN_EVENT.match(line)
        if one and _is_event(one.group(2)) and len(one.group(2)) < constants.MEET_SHEET_MAX_EVENT_CHARS:
            number = normalize_event_number(one.group(1))
            events.setdefault(number, ProgramEvent.from_description(number, one.group(2), course=course))
    return sorted(events.values(), key=lambda event: (int(re.sub(r"\D", "", event.number) or 0), event.number))


def _is_event(description: str) -> bool:
    """True if the text names a distance and a stroke ("Open 100 free")."""
    event = ProgramEvent.from_description("0", description)
    return event.stroke is not None and event.distance is not None


def _officials(text: str) -> list[dict[str, str]]:
    """Named officials ("Meet Referee: Pat Lee"), each with its roster role (None for e.g. Meet Director)."""
    officials = []
    seen = set()
    for title_pattern, role in OFFICIAL_TITLES:
        for match in re.finditer(rf"\b({title_pattern})[ \t]*[:\-–][ \t]*{_NAME}", text):
            name = match.group(2).strip()
            if name in seen:
                continue  # already found under a more specific title ("Meet Referee" before "Referee")
            seen.add(name)
            officials.append({"name": name, "role": role, "title": " ".join(match.group(1).split())})
    return officials


def _sessions(lines: list[str], text: str, days: list[date]) -> list[ProgramSession]:
    """Sessions with their start times: "Session N" lines, else one session from the warm-up/start times."""
    sessions = []
    for line in lines:
        match = SESSION_LINE.match(line)
        if not match:
            continue
        rest = match.group(2)
        start = START_PATTERN.search(rest) or re.search(rf"start\w*\s*(?:at\s*)?:?\s*{TIME}", rest, re.IGNORECASE)
        warmup = WARMUP_PATTERN.search(rest)
        day = next((day for day in days if day.strftime("%A").lower() in rest.lower()), None)
        session = ProgramSession(number=match.group(1), name=" ".join(rest.strip(" :-–").split())[:TITLE_MAX_CHARS],
                                 day=day.isoformat() if day else None)
        if start:
            session.start_time = _clock(start.group(1), start.group(2))
        elif warmup:
            session.start_time = _clock(warmup.group(3), warmup.group(4), warmup.group(2))
        sessions.append(session)
    if sessions:
        return sessions
    start = START_PATTERN.search(text)
    warmup = WARMUP_PATTERN.search(text)
    if not (start or warmup):
        return []
    session = ProgramSession(number="1", name="Session 1", day=days[0].isoformat() if days else None)
    if start:
        session.start_time = _clock(start.group(1), start.group(2), warmup.group(4) if warmup else None)
    else:
        session.start_time = _clock(warmup.group(3), warmup.group(4), warmup.group(2))
    if warmup:
        warmup_clock = datetime.strptime(_clock(warmup.group(1), warmup.group(2), warmup.group(4)), CLOCK_24_HOUR)
        session.name = f"Session 1 (warm-up {warmup_clock.strftime(constants.CLOCK_FORMAT_12_HOUR).lstrip('0')})"
    return [session]


def read_meet_sheet_text(text: str) -> MeetSheet:
    """Read a meet sheet given as text."""
    lines = [line.rstrip() for line in text.replace("\r", "").splitlines()]
    sheet = MeetSheet()
    sheet.name = next((" ".join(line.split()) for line in lines if line.strip()), "")[:TITLE_MAX_CHARS]
    sheet.dates = _meet_days(text)
    course = COURSE_PATTERN.search(text)
    if course:
        sheet.course = "Yard" if course.group(2).lower().startswith("y") else "Meter"
    location = next((LOCATION_PATTERN.match(line) for line in lines if LOCATION_PATTERN.match(line)), None)
    if location:
        sheet.location = " ".join(location.group(1).split())
    sheet.events = _events(lines, sheet.course)
    sheet.sessions = _sessions(lines, text, sheet.dates)
    for session in sheet.sessions:
        if len(sheet.sessions) == 1:
            session.event_numbers = [event.number for event in sheet.events]
            for event in sheet.events:
                event.session = session.number
    sheet.officials = _officials(text)
    for key, found in (("date", sheet.dates), ("sessions", sheet.sessions), ("events", sheet.events), ("officials", sheet.officials)):
        if not found:
            sheet.missing.append(NOT_FOUND[key])
    return sheet


def _docx_text(path: Path) -> str:
    """The text of a Word document (paragraphs as lines)."""
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml").decode("utf-8", errors="replace")
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab/>", "\t", xml)
    return html_text(re.sub(r"<[^>]+>", "", xml).replace("\n", "<br>"))


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


def _decode(raw: bytes) -> str:
    """Text from bytes: UTF-8 if valid, else Windows' usual encoding."""
    for encoding in TEXT_ENCODINGS:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode(TEXT_ENCODINGS[-1], errors="replace")


def _has_word_document(path: Path) -> bool:
    """True if a zip file is a Word document."""
    try:
        with zipfile.ZipFile(path) as archive:
            return "word/document.xml" in archive.namelist()
    except zipfile.BadZipFile:
        return False


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
