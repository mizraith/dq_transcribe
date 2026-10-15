"""DQ slip codes: the code table, and ranking slip lines against spoken words.

The infraction phrase list (``data/infraction_phrases.csv``) maps common radio
wording straight to slip codes. Anything it does not cover still gets useful
suggestions here: every line of the slip (its section, group and description,
e.g. "Backstroke / Past vertical at turn / Delay initiating turn") is scored by
how many of its words were heard, so "past vertical at turn" suggests 2B, 2C and
2D, and "one hand touch" suggests 1J and 3J.

Words are compared after light stemming ("delayed" = "delay", "strokes" =
"stroke") and without filler words ("the", "at", ...).
"""

from __future__ import annotations

import csv
import functools
import re

from dq_transcribe import constants

# Filler words that say nothing about the infraction. "no" and "not" are kept:
# they matter ("no touch", "not separated").
FILLER_WORDS = frozenset({
    "a", "an", "and", "at", "by", "did", "for", "had", "has", "he", "her", "his", "i", "in", "is", "it",
    "of", "or", "she", "that", "the", "their", "they", "this", "to", "was", "were", "with",
})
WORD_PATTERN = re.compile(r"[a-z0-9]+")
STEM_SUFFIXES = ("ing", "ed", "s")
MIN_STEM_LENGTH = 3
# A slip line is suggested when all of its group's words were heard (for groups
# of at least MIN_GROUP_WORDS words: "Kick" alone is too vague), all of its
# description's words were heard, or at least MIN_SHARED_WORDS of its words were.
MIN_SHARED_WORDS = 2
MIN_GROUP_WORDS = 2
SCORE_FULL_DESCRIPTION = 3.0
SCORE_FULL_GROUP = 2.0
DEFAULT_SUGGESTION_LIMIT = 6
# Sections always kept when the stroke is known (they apply to every stroke).
STROKE_INDEPENDENT_SECTIONS = frozenset({"Miscellaneous"})


def load_dq_codes(revision: str = constants.CURRENT_SLIP_REVISION) -> list[dict[str, str]]:
    """The DQ slip's code table for a revision (empty if the file is missing)."""
    path = constants.REFERENCE_DIRECTORY / "dq_codes" / constants.DQ_CODES_FILENAME_FORMAT.format(revision=revision)
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))
    except OSError:
        return []


@functools.lru_cache(maxsize=4)
def _cached_codes(revision: str) -> tuple[dict[str, str], ...]:
    """The code table, read once per revision."""
    return tuple(load_dq_codes(revision))


def stem(word: str) -> str:
    """Crude stem so spoken variants line up with slip wording.

    "delayed" -> "delay", "strokes"/"stroke" -> "strok", "touches" -> "touch",
    "initiating"/"initiate" -> "initiat". Both sides of every comparison are
    stemmed the same way, so the stems only need to be consistent, not words.
    """
    for suffix in STEM_SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= MIN_STEM_LENGTH and not word.endswith("ss"):
            word = word[: -len(suffix)]
            break
    if word.endswith("e") and len(word) > MIN_STEM_LENGTH + 1:
        word = word[:-1]
    return word


def key_words(text: str) -> set[str]:
    """Stemmed, meaningful words of a text ("hip line" also counts as "hipline")."""
    words = [word for word in WORD_PATTERN.findall(text.lower()) if word not in FILLER_WORDS]
    joined = {words[i] + words[i + 1] for i in range(len(words) - 1)}
    return {stem(word) for word in words} | {stem(word) for word in joined}


def _score(row: dict[str, str], heard: set[str]) -> float:
    """How well a slip line matches the heard words (0 = not a suggestion)."""
    group = key_words(row["group"])
    description = key_words(row["description"])
    group_hit = len(group) >= MIN_GROUP_WORDS and group <= heard
    description_hit = bool(description) and description <= heard
    if description_hit:
        return SCORE_FULL_DESCRIPTION + (len(group & heard) / len(group) if group else 0.0)
    if group_hit:
        # Every line of the group fits; prefer those whose own words were also heard.
        return SCORE_FULL_GROUP + len(description & heard) / len(description)
    shared = len((group | description) & heard)
    return shared / len(group | description) if shared >= MIN_SHARED_WORDS else 0.0


def rank_codes(
    text: str,
    stroke: str | None = None,
    limit: int = DEFAULT_SUGGESTION_LIMIT,
    revision: str = constants.CURRENT_SLIP_REVISION,
) -> list[str]:
    """Slip codes whose wording best matches a text, best first.

    Args:
        text: What was heard or typed (a call's transcript, or an infraction description).
        stroke: The race's stroke if known; other strokes' lines are then left out.
        limit: Most codes to return.
        revision: Slip revision whose codes to use.

    Returns:
        Codes such as ["2B", "2C", "2D", "2L"]; empty if nothing matches.
    """
    heard = key_words(text)
    if not heard:
        return []
    scored = []
    for position, row in enumerate(_cached_codes(revision)):
        if not row["code"]:
            continue
        if stroke and row["section"] != stroke and row["section"] not in STROKE_INDEPENDENT_SECTIONS:
            continue
        score = _score(row, heard)
        if score > 0:
            scored.append((-score, position, row["code"]))
    return [code for _, _, code in sorted(scored)[:limit]]
