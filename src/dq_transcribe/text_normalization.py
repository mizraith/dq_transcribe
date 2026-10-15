"""Turn spoken numbers in radio-call transcripts into digits.

Officials say numbers as words ("event one, heat two, lane three"), and whisper
writes them either way. This module rewrites the numbers that belong to event,
heat, lane, turn, swimmer and leg mentions as digits, so "Event, one, heat, two"
becomes "Event 1, heat 2". Number words elsewhere are left alone, so "one hand
touch" keeps its meaning.

Right after a keyword it also fixes common mishearings of numbers ("heat for"
-> "heat 4", "heat full" -> "heat 4"), and expands the short form "E46" to
"Event 46".
"""

from __future__ import annotations

import re

# Words after which numbers follow (singular and plural forms).
NUMBER_KEYWORDS = frozenset(
    {"event", "events", "heat", "heats", "lane", "lanes", "turn", "turns", "swimmer", "swimmers", "leg", "legs", "number"}
)
UNITS = {
    "zero": 0, "oh": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
ORDINALS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8,
    "ninth": 9, "tenth": 10,
}
# Words whisper writes for a number spoken right after a keyword ("heat for", "heat full").
NUMBER_SOUNDALIKES = {"for": 4, "fore": 4, "full": 4, "floor": 4, "to": 2, "too": 2, "won": 1, "ate": 8, "tree": 3}
# Words that may sit between numbers in a list ("lanes 1, 3 and 4").
LIST_JOINERS = frozenset({"and", "&", ",", "or"})
# "E46" is short for "Event 46".
EVENT_SHORT_FORM = re.compile(r"^[Ee](\d+)$")
TOKEN_PATTERN = re.compile(r"[Ee]\d+\b|[A-Za-z]+(?:'[A-Za-z]+)?|\d+(?:st|nd|rd|th)?|[^\sA-Za-z\d]")
# A number word followed by one of these is part of a phrase, not a count:
# "one hand touch" stays as words.
PHRASE_FOLLOWERS = frozenset({"hand", "handed", "hands"})
ORDINAL_SUFFIXES = {1: "st", 2: "nd", 3: "rd"}
EVENT_WORD = "Event"


def ordinal_text(value: int) -> str:
    """Write an ordinal number with digits, for example 3 -> "3rd"."""
    suffix = "th" if 10 <= value % 100 <= 20 else ORDINAL_SUFFIXES.get(value % 10, "th")
    return f"{value}{suffix}"


def _read_number(tokens: list[str], index: int, allow_soundalike: bool) -> tuple[int, int] | None:
    """Read a number starting at ``tokens[index]``.

    Args:
        tokens: Tokens of the text.
        index: Where the number may start.
        allow_soundalike: Also accept words like "for" (only directly after a keyword).

    Returns:
        ``(value, tokens_used)``, or None if no number starts here.
    """
    if index >= len(tokens):
        return None
    if index + 1 < len(tokens) and tokens[index + 1].lower() in PHRASE_FOLLOWERS:
        return None
    word = tokens[index].lower()
    if word.isdigit():
        return int(word), 1
    if word in TENS:
        if index + 1 < len(tokens) and tokens[index + 1].lower() in UNITS and UNITS[tokens[index + 1].lower()] < 10:
            return TENS[word] + UNITS[tokens[index + 1].lower()], 2
        return TENS[word], 1
    if word in UNITS:
        return UNITS[word], 1
    if allow_soundalike and word in NUMBER_SOUNDALIKES:
        return NUMBER_SOUNDALIKES[word], 1
    return None


def tokenize(text: str) -> list[str]:
    """Split text into words, numbers and punctuation marks."""
    return TOKEN_PATTERN.findall(text)


def _tokens_with_spacing(text: str) -> tuple[list[str], list[str], str]:
    """Tokens, the text before each token (spacing), and any trailing text."""
    tokens: list[str] = []
    spacing: list[str] = []
    position = 0
    for match in TOKEN_PATTERN.finditer(text):
        spacing.append(text[position:match.start()])
        tokens.append(match.group())
        position = match.end()
    return tokens, spacing, text[position:]


def normalize_spoken_numbers(text: str) -> str:
    """Rewrite event, heat, lane, turn, swimmer and leg numbers as digits.

    Examples:
        "Event, one, heat, two, lane, three" -> "Event 1, heat 2, lane 3"
        "lanes one, three, and four" -> "lanes 1, 3, and 4"
        "heat for lane five" -> "heat 4 lane 5"
        "the third turn" -> "the 3rd turn"
        "E46" -> "Event 46"
        "one hand touch" and "on the turn, one hand touch" -> unchanged

    Args:
        text: Transcript text.

    Returns:
        The text with those numbers written as digits.
    """
    tokens, spacing, trailing = _tokens_with_spacing(text)
    output: list[str] = []  # alternating spacing and token text, joined at the end
    index = 0
    while index < len(tokens):
        token = tokens[index]
        short_form = EVENT_SHORT_FORM.match(token)
        if short_form:
            output.extend([spacing[index], EVENT_WORD, " ", short_form.group(1)])
            index += 1
            continue
        lowered = token.lower()
        if lowered in ORDINALS and index + 1 < len(tokens) and tokens[index + 1].lower() in ("turn", "turns"):
            output.extend([spacing[index], ordinal_text(ORDINALS[lowered])])
            index += 1
            continue
        output.extend([spacing[index], token])
        index += 1
        if lowered not in NUMBER_KEYWORDS:
            continue
        # Numbers after a keyword: skip a comma whisper put between the keyword and
        # the number, then read a list such as "1, 3, and 4".
        first = True
        while index < len(tokens):
            look = index
            while look < len(tokens) and tokens[look] == ",":
                look += 1
            number = _read_number(tokens, look, allow_soundalike=first)
            if number is None:
                break
            value, used = number
            # Skipped commas are dropped ("Event, one" -> "Event 1").
            output.extend([spacing[look] or " ", str(value)])
            index = look + used
            first = False
            # Continue through list joiners if another number follows.
            joiner_end = index
            joiners: list[str] = []  # list words such as "and" between numbers
            while joiner_end < len(tokens) and tokens[joiner_end].lower() in LIST_JOINERS:
                joiners.append(tokens[joiner_end])
                joiner_end += 1
            if joiners and _read_number(tokens, joiner_end, allow_soundalike=False) is not None:
                for joiner_index in range(index, joiner_end):
                    output.extend([spacing[joiner_index], tokens[joiner_index]])
                index = joiner_end
            else:
                break
    return "".join(output) + trailing
