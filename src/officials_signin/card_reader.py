"""Parse the text of a USA Swimming membership card read by OCR.

The browser photographs the official's phone (the USA Swimming app's
"Membership card" tab), runs Tesseract.js on each camera frame, and posts the
text of every pass here. Each pass is parsed on its own, then the passes are
merged by vote, because each OCR pass tends to get different parts right:
one reads the member ID, another the dates.

The card looks like this (labels fixed, values vary)::

    In good standing
    Official
    MARK "RED" BYER
    Member Id: [member ID removed]
    LSC & Club: PC - PASA
    In Good Standing Until: 09/21/2027
    Expiration Date: 12/31/9999
    Background Check: 09/30/2027
    Athlete Protection Training: 09/21/2027

Nothing in this module logs the member ID or the name.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Iterable

from officials_signin import constants

_FLAGS = re.IGNORECASE
_SEPARATOR = r"\s*[:;.,]?\s*"
_DATE_VALUE = r"(\d{1,2})\s*[/|\\]\s*(\d{1,2})\s*[/|\\]\s*(\d{4})"

_DATE_PATTERNS = {
    field_name: re.compile(label + r"[^0-9\n]{0,6}" + _DATE_VALUE, _FLAGS)
    for field_name, label in constants.CARD_DATE_LABEL_PATTERNS.items()
}
_MEMBER_ID_PATTERN = re.compile(
    constants.CARD_MEMBER_ID_LABEL_PATTERN
    + _SEPARATOR
    + rf"([A-Z0-9]{{{constants.CARD_MEMBER_ID_MIN_LENGTH},{constants.CARD_MEMBER_ID_MAX_LENGTH}}})\b",
    _FLAGS,
)
_MEMBER_ID_LABEL = re.compile(constants.CARD_MEMBER_ID_LABEL_PATTERN, _FLAGS)
_LSC_CLUB_PATTERN = re.compile(
    constants.CARD_LSC_CLUB_LABEL_PATTERN
    + _SEPARATOR
    + rf"([A-Z]{{{constants.CARD_LSC_CODE_LENGTH}}})\s*[-–—~=]+\s*([A-Z0-9]{{2,{constants.CARD_CLUB_CODE_MAX_LENGTH}}})\b",
    _FLAGS,
)
_OFFICIAL_PATTERN = re.compile(constants.CARD_OFFICIAL_PATTERN, _FLAGS)
_GOOD_STANDING_BANNER_PATTERN = re.compile(constants.CARD_GOOD_STANDING_BANNER_PATTERN, _FLAGS)
_NAME_CHARACTERS = re.compile(r"[^A-Za-z\"'’.\- ]")
_LETTER_RUN = re.compile(r"[A-Za-z]+")
_NAME_WORD = re.compile(r"[A-Za-z][A-Za-z'’.\-]*")


@dataclass
class CardReading:
    """What could be read from one card (one OCR pass, or several merged).

    Dates are ISO strings (``YYYY-MM-DD``). Any field may be None when it was
    not read.

    Attributes:
        name: Name as printed, tidied to title case (``Mark "Red" Byer``).
        member_id: USA Swimming member ID, upper case. Personal data: never log it.
        lsc: Two-letter LSC code, for example ``PC``.
        club: Club code, for example ``PASA``.
        good_standing_until: "In Good Standing Until" date.
        expiration_date: "Expiration Date" (often 12/31/9999).
        background_check_until: Background check expiry date.
        athlete_protection_until: Athlete protection training expiry date.
        is_official: True when the card says "Official".
        good_standing_banner: True when the green "In good standing" banner was read.
        labels_found: How many card labels were recognised (0 means the text is
            probably not a membership card, or the image is mirrored).
    """

    name: str | None = None
    member_id: str | None = None
    lsc: str | None = None
    club: str | None = None
    good_standing_until: str | None = None
    expiration_date: str | None = None
    background_check_until: str | None = None
    athlete_protection_until: str | None = None
    is_official: bool = False
    good_standing_banner: bool = False
    labels_found: int = 0

    @property
    def missing_fields(self) -> list[str]:
        """Required fields not read yet, in ``constants.CARD_REQUIRED_FIELDS`` order."""
        return [name for name in constants.CARD_REQUIRED_FIELDS if getattr(self, name) is None]

    @property
    def is_complete(self) -> bool:
        """True when every required field has been read."""
        return not self.missing_fields

    @property
    def zone(self) -> str | None:
        """USA Swimming zone for the card's LSC, or None if unknown."""
        return None if self.lsc is None else constants.ZONE_BY_LSC_CODE.get(self.lsc)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready dictionary including the derived fields."""
        result = asdict(self)
        result[constants.KEY_ZONE] = self.zone
        result[constants.CARD_FIELD_COMPLETE] = self.is_complete
        result[constants.CARD_FIELD_MISSING] = self.missing_fields
        return result


def _parse_card_date(month: str, day: str, year: str) -> str | None:
    """Turn month/day/year text into an ISO date, or None if it is not a real date."""
    try:
        return datetime.strptime(f"{month}/{day}/{year}", constants.CARD_DATE_INPUT_FORMAT).date().isoformat()
    except ValueError:
        return None


def tidy_name(raw_name: str) -> str:
    """Tidy a name read from the card: drop stray symbols and use title case.

    Words inside quotes (a nickname) keep their quotes, so
    ``MARK "RED" BYER`` becomes ``Mark "Red" Byer`` and ``MARY-JO O'NEIL``
    becomes ``Mary-Jo O'Neil`` (names like McDonald lose their inner capital).

    Args:
        raw_name: Name text as read by OCR.

    Returns:
        The tidied name, at most ``constants.NAME_MAX_LENGTH`` characters.
    """
    cleaned = _NAME_CHARACTERS.sub(" ", raw_name).replace("’", "'")
    words = [word for word in cleaned.split() if any(character.isalpha() for character in word)]
    # Capitalise each run of letters, so hyphenated names and O' names come out right.
    tidied_words = [_LETTER_RUN.sub(lambda match: match.group(0).capitalize(), word) for word in words]
    return " ".join(tidied_words)[: constants.NAME_MAX_LENGTH]


def _looks_like_name(line: str) -> bool:
    """True when an OCR line could be the member's name (not a label or noise)."""
    if any(character.isdigit() for character in line):
        return False
    words = _NAME_WORD.findall(line)
    if len(words) < constants.CARD_NAME_MIN_WORDS:
        return False
    if any(word.lower().strip(".") in constants.CARD_NON_NAME_WORDS for word in words):
        return False
    visible = [character for character in line if not character.isspace()]
    letter_share = sum(character.isalpha() for character in visible) / len(visible)
    return letter_share >= constants.CARD_NAME_MIN_LETTER_SHARE


def _find_name(lines: list[str]) -> str | None:
    """Find the name: the last name-like line between "Official" and "Member Id".

    When neither anchor is in the text, no name is guessed (too risky).
    """
    member_line = next((index for index, line in enumerate(lines) if _MEMBER_ID_LABEL.search(line)), None)
    official_line = next((index for index, line in enumerate(lines) if _OFFICIAL_PATTERN.search(line)), None)
    if member_line is None and official_line is None:
        return None
    start = 0 if official_line is None else official_line + 1
    end = len(lines) if member_line is None else member_line
    if official_line is not None and member_line is not None and official_line > member_line:
        start = 0
    candidates = [line for line in lines[start:end] if _looks_like_name(line)]
    if not candidates:
        return None
    # Between the anchors the name is the line just above "Member Id"; after
    # "Official" alone, it is the first line below it.
    chosen = candidates[-1] if member_line is not None else candidates[0]
    return tidy_name(chosen) or None


def parse_card_text(text: str) -> CardReading:
    """Parse the text of one OCR pass over a membership card.

    Args:
        text: Raw OCR output (lines separated by newlines).

    Returns:
        Everything that could be read; unread fields are None.
    """
    reading = CardReading()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    labels_found = 0

    for field_name, pattern in _DATE_PATTERNS.items():
        match = pattern.search(text)
        if match is not None:
            setattr(reading, field_name, _parse_card_date(*match.groups()))
        if re.search(constants.CARD_DATE_LABEL_PATTERNS[field_name], text, _FLAGS):
            labels_found += 1

    member_match = _MEMBER_ID_PATTERN.search(text)
    if member_match is not None:
        reading.member_id = member_match.group(1).upper()
    if _MEMBER_ID_LABEL.search(text):
        labels_found += 1

    lsc_match = _LSC_CLUB_PATTERN.search(text)
    if lsc_match is not None:
        reading.lsc = lsc_match.group(1).upper()
        reading.club = lsc_match.group(2).upper()
    if re.search(constants.CARD_LSC_CLUB_LABEL_PATTERN, text, _FLAGS):
        labels_found += 1

    reading.is_official = _OFFICIAL_PATTERN.search(text) is not None
    reading.good_standing_banner = _GOOD_STANDING_BANNER_PATTERN.search(text) is not None
    reading.name = _find_name(lines)
    reading.labels_found = labels_found
    return reading


def _most_common(values: Iterable[Any]) -> Any:
    """Return the most frequent non-None value (earliest wins a tie), or None."""
    present = [value for value in values if value is not None]
    if not present:
        return None
    counts = Counter(present)
    best_count = max(counts.values())
    return next(value for value in present if counts[value] == best_count)


def merge_readings(readings: list[CardReading]) -> CardReading:
    """Merge several OCR passes of the same card by majority vote per field.

    Args:
        readings: Parsed passes, in the order they were taken.

    Returns:
        One reading. Booleans are True if any pass saw them; ``labels_found`` is
        the best single pass.
    """
    merged = CardReading()
    for field_name in (
        constants.CARD_FIELD_NAME,
        constants.CARD_FIELD_MEMBER_ID,
        constants.CARD_FIELD_GOOD_STANDING_UNTIL,
        constants.CARD_FIELD_EXPIRATION,
        constants.CARD_FIELD_BACKGROUND_CHECK,
        constants.CARD_FIELD_ATHLETE_PROTECTION,
    ):
        setattr(merged, field_name, _most_common(getattr(reading, field_name) for reading in readings))
    # LSC and club are read together, so vote on the pair.
    pair = _most_common(
        (reading.lsc, reading.club) if reading.lsc is not None else None for reading in readings
    )
    if pair is not None:
        merged.lsc, merged.club = pair
    merged.is_official = any(reading.is_official for reading in readings)
    merged.good_standing_banner = any(reading.good_standing_banner for reading in readings)
    merged.labels_found = max((reading.labels_found for reading in readings), default=0)
    return merged


def read_card(texts: list[str]) -> CardReading:
    """Parse and merge the text of every OCR pass over one card.

    Args:
        texts: OCR output of each pass.

    Returns:
        The merged reading.
    """
    return merge_readings([parse_card_text(text) for text in texts])


@dataclass
class CardCheck:
    """Whether a card reading validates an official for a session date.

    Attributes:
        validated: True when every required date is current on the session date.
        problems: Human-readable reasons when not validated (for the admin).
    """

    validated: bool
    problems: list[str] = field(default_factory=list)


def check_card(reading: CardReading, on_date: date) -> CardCheck:
    """Decide whether a card reading validates the official on a given date.

    Membership, background check and athlete protection training must each be
    current (not before ``on_date``). This confirms membership and safety
    requirements only, not position certifications (the Referee assigns positions).

    Args:
        reading: Merged card reading.
        on_date: The session date.

    Returns:
        The decision and, if not validated, the reasons.
    """
    problems = []
    for field_name, label in constants.CARD_DATES_REQUIRED_CURRENT.items():
        value = getattr(reading, field_name)
        if value is None:
            problems.append(f"{label}: not read")
        elif date.fromisoformat(value) < on_date:
            problems.append(f"{label}: expired {value}")
    if reading.member_id is None:
        problems.append("Member ID: not read")
    return CardCheck(validated=not problems, problems=problems)
