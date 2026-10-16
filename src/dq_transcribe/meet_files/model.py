"""The meet program read from a Meet Manager file: events, entries and sessions.

Every importer (Hy-Tek database, PDF report, HTML report) produces the same
``MeetProgram``, so the rest of the app never cares which file it came from.

What the app uses it for:

* **Auto-fill:** a DQ's event, heat and lane look up the swimmer (or relay) and
  club, so the admin rarely types a name.
* **Event details:** each event's stroke, distance, gender and age group. A known
  stroke lets the call detector pick the right slip code ("one hand touch" is 3J
  in breaststroke, 1J in butterfly).
* **Sessions:** which events are in which session, when the file says so.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from dq_transcribe import constants

# Spoken/printed stroke names, longest first, mapped to the app's stroke names.
_STROKE_PATTERNS = (
    (re.compile(r"\bmed(?:ley)?\.?\s+relay\b", re.IGNORECASE), constants.STROKE_MEDLEY_RELAY),
    (re.compile(r"\b(?:free(?:style)?|free)\s+relay\b", re.IGNORECASE), constants.STROKE_FREESTYLE_RELAY),
    (re.compile(r"\b(?:individual\s+medley|IM)\b", re.IGNORECASE), constants.STROKE_INDIVIDUAL_MEDLEY),
    (re.compile(r"\b(?:butterfly|fly)\b", re.IGNORECASE), constants.STROKE_BUTTERFLY),
    (re.compile(r"\b(?:backstroke|back)\b", re.IGNORECASE), constants.STROKE_BACKSTROKE),
    (re.compile(r"\b(?:breaststroke|breast)\b", re.IGNORECASE), constants.STROKE_BREASTSTROKE),
    (re.compile(r"\b(?:freestyle|free)\b", re.IGNORECASE), constants.STROKE_FREESTYLE),
)
_DISTANCE_PATTERN = re.compile(r"\b(\d{2,4})\s*(Yard|Yd|Y|Meter|M|LC\s*Meter|SC\s*Meter)\b", re.IGNORECASE)
# A distance written without a unit, right before the stroke ("Open 100 free" on a meet sheet).
_BARE_DISTANCE_PATTERN = re.compile(r"\b(\d{2,4})\s+(?=(?:free|back|breast|fly|butterfly|im\b|individual|medley|med\b))", re.IGNORECASE)
_GENDER_PATTERN = re.compile(r"\b(Girls|Boys|Women|Men|Mixed|Female|Male)\b", re.IGNORECASE)
_AGE_GROUP_PATTERN = re.compile(
    r"\b(\d{1,2}\s*(?:&|and)\s*(?:Under|Over|Up)\b|\d{1,2}\s*-\s*\d{1,2}\b|\d{1,2}\+|Open\b|Senior\b)", re.IGNORECASE
)
_RELAY_WORD = "relay"
# Club codes are often printed with the swimming region (LSC): "PASA-PC".
_CLUB_REGION_SUFFIX = re.compile(r"-[A-Z]{2}$")


OPEN_AGE_GROUP = "open"


# "13 & Over", "13 and over", "13/over", "13 & Up" are shown as "13+" (owner's preference).
_OVER_AGE_GROUP = re.compile(r"^(\d{1,2})\s*(?:&|and|/|-)?\s*(?:over|up|o)$", re.IGNORECASE)
AGE_OVER_FORMAT = "{age}+"


def _age_group(text: str) -> str | None:
    """"8 & under" -> "8 & Under"; "13 & Over" -> "13+"; "Open" -> None (reports print no age group for open events)."""
    label = " ".join(text.split())
    over = _OVER_AGE_GROUP.match(label)
    if over:
        return AGE_OVER_FORMAT.format(age=over.group(1))
    label = label.title()
    return None if label.lower() == OPEN_AGE_GROUP else label


def stroke_from_description(description: str) -> str | None:
    """The stroke named in an event description ("Girls 10 & Under 50 Yard Breaststroke")."""
    for pattern, stroke in _STROKE_PATTERNS:
        if pattern.search(description):
            return stroke
    return None


def stroke_for_slip_codes(stroke: str | None) -> str | None:
    """The single stroke every swimmer in the event swims, for choosing slip codes.

    None for IM and medley relays (each swimmer's stroke depends on the leg).
    """
    if stroke in constants.SINGLE_STROKES:
        return stroke
    if stroke == constants.STROKE_FREESTYLE_RELAY:
        return constants.STROKE_FREESTYLE
    return None


def club_code(team: str) -> str:
    """"PASA-PC" -> "PASA" (the club code without the region)."""
    return _CLUB_REGION_SUFFIX.sub("", team.strip())


def format_swimmer_name(first: str, last: str) -> str:
    """A swimmer's name as written on a DQ (see ``SWIMMER_NAME_FORMAT``)."""
    if (first + last).isupper():
        first, last = first.title(), last.title()  # some databases store a name in capitals
    if not first:
        return last.strip()
    return constants.SWIMMER_NAME_FORMAT.format(first=first.strip(), last=last.strip()).strip(" ,")


def normalize_event_number(number: str | int) -> str:
    """"012" -> "12", " 2B " -> "2b": event numbers compared as text."""
    text = str(number).strip().lower()
    match = re.match(r"^0*(\d+)([a-z]?)$", text)
    return f"{int(match.group(1))}{match.group(2)}" if match else text


@dataclass
class ProgramEvent:
    """One event of the meet."""

    number: str
    description: str = ""
    gender: str | None = None
    age_group: str | None = None
    distance: int | None = None
    course: str | None = None  # "Yard" or "Meter"
    stroke: str | None = None
    relay: bool = False
    session: str | None = None
    round: str | None = None  # "Prelims", "Finals", "Timed Finals"

    @classmethod
    def from_description(cls, number: str, description: str, **extra: Any) -> ProgramEvent:
        """Build an event, reading gender, age group, distance and stroke from its description.

        ``course`` may be passed in ``extra`` for descriptions without a unit
        ("Open 100 free" on a meet sheet that says the pool is 25 yards).
        """
        description = " ".join(description.split())
        gender = _GENDER_PATTERN.search(description)
        age = _AGE_GROUP_PATTERN.search(description)
        distance = _DISTANCE_PATTERN.search(description)
        course = extra.pop("course", None)
        distance_value = None
        if distance:
            course = "Yard" if distance.group(2).lower().startswith("y") else "Meter"
            distance_value = int(distance.group(1))
        elif (bare := _BARE_DISTANCE_PATTERN.search(description)) is not None:
            distance_value = int(bare.group(1))
        return cls(
            number=normalize_event_number(number),
            description=description,
            gender=gender.group(1).title() if gender else None,
            age_group=_age_group(age.group(1)) if age else None,
            distance=distance_value,
            course=course,
            stroke=stroke_from_description(description),
            relay=_RELAY_WORD in description.lower(),
            **extra,
        )

    @property
    def short_label(self) -> str:
        """"Girls 10 & Under 50 Breaststroke" style label, or the description."""
        parts = [self.gender, self.age_group, str(self.distance) if self.distance else None, self.stroke]
        label = " ".join(part for part in parts if part)
        return label or self.description


@dataclass
class ProgramEntry:
    """A swimmer or relay seeded in a heat and lane."""

    event_number: str
    heat: str
    lane: str
    swimmer: str  # display name, or the relay's name ("PASA-A")
    club: str = ""
    age: int | None = None
    seed_time: str = ""
    relay: bool = False
    relay_swimmers: list[str] = field(default_factory=list)
    round: str | None = None


@dataclass
class ProgramSession:
    """A session of the meet, when the file names them."""

    number: str
    name: str = ""
    day: str | None = None  # date (YYYY-MM-DD) or day label
    start_time: str | None = None
    event_numbers: list[str] = field(default_factory=list)


@dataclass
class MeetProgram:
    """Everything read from one Meet Manager file."""

    meet_name: str = ""
    events: list[ProgramEvent] = field(default_factory=list)
    entries: list[ProgramEntry] = field(default_factory=list)
    sessions: list[ProgramSession] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        """Counts shown after loading ("42 events, 612 entries, 4 sessions")."""
        return {
            "meet_name": self.meet_name,
            "events": len(self.events),
            "entries": len(self.entries),
            "heats": len({(entry.event_number, entry.heat, entry.round) for entry in self.entries}),
            "sessions": len(self.sessions),
            "warnings": self.warnings[:20],
        }

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly form."""
        return asdict(self)
