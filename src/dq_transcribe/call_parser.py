"""Find DQ calls in radio transcripts (rule-based, no AI).

One clip, or one call/response group of clips, can hold several calls: several
lanes ("lanes 1, 3 and 4, scissors kick"), several infractions, add-ons ("and
lane 6 had a one hand touch"), corrections ("heat 4, sorry, heat 2") and
acknowledgments ("Accepted"). This module turns the transcript of a group into a
list of *candidate calls*, one per lane, each pointing back at the turns it came
from. Nothing is copied: a candidate records the clip, utterance and time range
it was heard in, so several DQs can share one clip.

Candidates are suggestions for the admin to confirm, never final answers. Each
carries flags explaining anything uncertain (a missing heat, an event carried
over from an earlier call, a correction, a fuzzy infraction match).

Infraction phrases come from ``data/infraction_phrases.csv`` (spoken variants
mapped to slip descriptions), so the vocabulary can grow without code changes.
"""

from __future__ import annotations

import csv
import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dq_transcribe.text_normalization import normalize_spoken_numbers, tokenize

PHRASES_PATH = Path(__file__).parent / "data" / "infraction_phrases.csv"

# Similarity needed for a fuzzy phrase match (1.0 = exact). Short phrases must
# match exactly, since a loose match on two words is too often wrong
# ("have to touch" is not "no touch").
PHRASE_MATCH_MIN_RATIO = 0.82
FUZZY_MIN_PHRASE_CHARACTERS = 12
# An utterance containing one of these is (also) an acknowledgment by the referee.
ACK_KEY_WORDS = frozenset({"accepted", "acknowledged", "confirmed", "copy", "roger"})
ACK_KEY_PHRASES = (("got", "it"), ("got", "that"))
# Words that mean "replace what I just said".
CORRECTION_WORDS = frozenset({"sorry", "correction", "mean", "scratch", "think"})
PHASE_WORDS = {"start": "Start", "swim": "Swim", "turn": "Turn", "finish": "Finish", "touch": None}
TURN_NUMBER_PATTERN = re.compile(r"\b(?:turn(?: number)? (\d+)|(\d+)(?:st|nd|rd|th) turn)\b")
KEY_EVENT, KEY_HEAT, KEY_LANE = "event", "heat", "lane"
KEYWORD_TO_KEY = {"event": KEY_EVENT, "events": KEY_EVENT, "heat": KEY_HEAT, "heats": KEY_HEAT, "lane": KEY_LANE, "lanes": KEY_LANE}
LIST_JOINERS = frozenset({"and", ",", "&"})

FLAG_EVENT_MISSING = "event not heard"
FLAG_HEAT_MISSING = "heat not heard"
FLAG_LANE_MISSING = "lane not heard"
FLAG_EVENT_CARRIED = "event taken from an earlier call"
FLAG_HEAT_CARRIED = "heat taken from an earlier call"
FLAG_CORRECTED = "the caller corrected a number"
FLAG_NO_INFRACTION = "infraction not recognized"
FLAG_NOT_UNDERSTOOD = "call not understood; listen to the audio"
# An utterance this long with nothing recognized is still shown, so no call is lost.
UNDERSTOOD_MIN_WORDS = 4
FLAG_FUZZY = "infraction matched loosely"


@dataclass(frozen=True)
class InfractionPhrase:
    """A spoken phrase that names an infraction."""

    words: tuple[str, ...]
    description: str
    stroke: str


@dataclass
class Evidence:
    """Where a candidate call was heard: a span of one utterance (no audio copied)."""

    clip_id: int
    utterance_id: int
    start_seconds: float
    end_seconds: float
    role: str  # "call" or "acknowledgment"


@dataclass
class CandidateCall:
    """One suggested DQ: a single lane with its infractions and its sources."""

    event: str | None = None
    heat: str | None = None
    lane: str | None = None
    infractions: list[str] = field(default_factory=list)
    strokes: list[str] = field(default_factory=list)
    phases: list[str] = field(default_factory=list)
    turn_number: str | None = None
    accepted: bool = False
    flags: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    excerpt: str = ""

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly form."""
        return {
            "event": self.event, "heat": self.heat, "lane": self.lane, "infractions": self.infractions,
            "strokes": self.strokes, "phases": self.phases, "turn_number": self.turn_number,
            "accepted": self.accepted, "flags": self.flags, "excerpt": self.excerpt,
            "evidence": [vars(item) for item in self.evidence],
        }


def load_phrases(path: Path = PHRASES_PATH) -> list[InfractionPhrase]:
    """Read the spoken infraction phrases, longest first (so the most specific phrase wins)."""
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    phrases = [
        InfractionPhrase(tuple(_words(row["phrase"])), row["description"], row["stroke"] or "") for row in rows
    ]
    return sorted(phrases, key=lambda phrase: -len(phrase.words))


def _words(text: str) -> list[str]:
    """Lower-case words and numbers of a text, without punctuation."""
    return [token.lower() for token in tokenize(text) if token[0].isalnum()]


def is_acknowledgment(text: str) -> bool:
    """True if the text acknowledges a call ("Accepted.", "Got it.", "Roger that.").

    The same utterance may also repeat call details ("Got it. Accepted. Lane 5 and 6.").
    """
    words = _words(text)
    if ACK_KEY_WORDS & set(words):
        return True
    return any(tuple(words[i:i + 2]) == phrase for phrase in ACK_KEY_PHRASES for i in range(len(words) - 1))


def find_infractions(words: list[str], phrases: list[InfractionPhrase]) -> list[tuple[int, InfractionPhrase, float]]:
    """Find infraction phrases in a word list (exact or close matches, no overlaps).

    Returns:
        ``(word_index, phrase, similarity)`` for each match, in text order.
    """
    taken = [False] * len(words)
    matches: list[tuple[int, InfractionPhrase, float]] = []
    for phrase in phrases:
        size = len(phrase.words)
        target = " ".join(phrase.words)
        allow_fuzzy = len(target) >= FUZZY_MIN_PHRASE_CHARACTERS
        # Also try one extra word, so "shoulders were past vertical" matches "shoulders past vertical".
        for window_size in (size, size + 1) if allow_fuzzy else (size,):
            for start in range(0, len(words) - window_size + 1):
                if any(taken[start:start + window_size]):
                    continue
                window = " ".join(words[start:start + window_size])
                if window == target:
                    ratio = 1.0
                elif allow_fuzzy:
                    ratio = difflib.SequenceMatcher(None, window, target).ratio()
                else:
                    continue
                if ratio >= PHRASE_MATCH_MIN_RATIO:
                    matches.append((start, phrase, ratio))
                    for position in range(start, start + window_size):
                        taken[position] = True
    return sorted(matches, key=lambda match: match[0])


@dataclass
class _LaneGroup:
    """Lanes named together, and everything said about them."""

    start: int
    lanes: list[str]
    event: str | None
    heat: str | None
    corrected: bool = False
    infractions: list[tuple[int, InfractionPhrase, float]] = field(default_factory=list)


def _read_numbers(words: list[str], index: int, key: str) -> tuple[list[str], int]:
    """Read a number list starting at ``index``; return (numbers, next index).

    Event and heat take one number. Lanes take a list: "1 3 and 4" or "6 and lane 7".
    """
    numbers: list[str] = []
    while index < len(words) and words[index].isdigit():
        numbers.append(words[index])
        index += 1
        if key != KEY_LANE:
            break
        if index + 1 < len(words) and words[index] in LIST_JOINERS and words[index + 1].isdigit():
            index += 1
        elif (
            index + 2 < len(words)
            and words[index] in LIST_JOINERS
            and words[index + 1] in ("lane", "lanes")
            and words[index + 2].isdigit()
        ):
            index += 2  # "lane 6 and lane 7"
        elif index + 1 < len(words) and words[index] in ("lane", "lanes") and words[index + 1].isdigit():
            index += 1
    return numbers, index


def parse_utterance(text: str, phrases: list[InfractionPhrase]) -> tuple[list[_LaneGroup], dict[str, str | None], bool]:
    """Split one utterance into lane groups.

    Returns:
        ``(lane_groups, last_event_and_heat, saw_correction)``.
    """
    words = [word for word in _words(normalize_spoken_numbers(text))]
    # Keep "and" between numbers; _words drops commas, which is fine for reading lists.
    context: dict[str, str | None] = {KEY_EVENT: None, KEY_HEAT: None}
    groups: list[_LaneGroup] = []
    infraction_matches = find_infractions(words, phrases)
    infraction_positions = [match[0] for match in infraction_matches]

    def infraction_since(start: int, end: int) -> bool:
        """True if an infraction was named between two word positions."""
        return any(start <= position < end for position in infraction_positions)

    correction_pending = False
    saw_correction = False
    index = 0
    while index < len(words):
        word = words[index]
        if word in CORRECTION_WORDS or (word == "or" and index + 1 < len(words) and words[index + 1] in ("is", "was")):
            correction_pending = True
            saw_correction = True
        key = KEYWORD_TO_KEY.get(word)
        if key is None:
            index += 1
            continue
        numbers, next_index = _read_numbers(words, index + 1, key)
        if not numbers:
            index += 1
            continue
        if key in (KEY_EVENT, KEY_HEAT):
            # A later event or heat (said before any infraction) applies to the lanes
            # already named; a second one replaces the first ("event 30, I think event 35").
            for group in groups:
                if infraction_since(group.start, index):
                    continue
                current = group.event if key == KEY_EVENT else group.heat
                if current is not None and current != numbers[0]:
                    group.corrected = True
                if key == KEY_EVENT:
                    group.event = numbers[0]
                else:
                    group.heat = numbers[0]
            context[key] = numbers[0]
        else:
            previous = groups[-1] if groups else None
            previous_is_open = previous is not None and not infraction_since(previous.start, index)
            if previous_is_open and correction_pending:
                previous.lanes = numbers  # "lane 3 ... sorry ... lane 4"
                previous.corrected = True
                previous.heat = context[KEY_HEAT]
            elif previous_is_open:
                previous.lanes.extend(lane for lane in numbers if lane not in previous.lanes)
            else:
                groups.append(_LaneGroup(index, list(numbers), context[KEY_EVENT], context[KEY_HEAT]))
            correction_pending = False
        index = next_index
    for match in infraction_matches:
        position = match[0]
        before = [group for group in groups if group.start <= position]
        target = before[-1] if before else (groups[0] if groups else None)
        if target is None:
            target = _LaneGroup(position, [], context[KEY_EVENT], context[KEY_HEAT])
            groups.append(target)
        target.infractions.append(match)
    return groups, context, saw_correction


def _phases_and_turn(text: str) -> tuple[list[str], str | None]:
    """Race phases (Start/Swim/Turn/Finish) and a turn number mentioned in a text."""
    normalized = normalize_spoken_numbers(text).lower()
    words = set(_words(normalized))
    phases = [label for word, label in PHASE_WORDS.items() if label and word in words]
    match = TURN_NUMBER_PATTERN.search(normalized)
    turn_number = (match.group(1) or match.group(2)) if match else None
    return phases, turn_number


def parse_call_group(utterances: list[dict[str, Any]], phrases: list[InfractionPhrase] | None = None) -> list[CandidateCall]:
    """Turn the utterances of one call/response group into candidate calls.

    Args:
        utterances: In time order; each needs ``clip_id``, ``id``, ``start_seconds``,
            ``end_seconds`` and ``text``.
        phrases: Infraction phrases (loaded from the data file if omitted).

    Returns:
        One candidate per lane (merged when the same lane is called twice in the group).
    """
    phrases = phrases if phrases is not None else load_phrases()
    calls: list[CandidateCall] = []
    group_context: dict[str, str | None] = {KEY_EVENT: None, KEY_HEAT: None}
    unacknowledged: list[CandidateCall] = []
    for utterance in utterances:
        text = utterance["text"]
        span = Evidence(utterance["clip_id"], utterance["id"], utterance["start_seconds"], utterance["end_seconds"], "call")
        if is_acknowledgment(text):
            for call in unacknowledged:
                call.accepted = True
                call.evidence.append(Evidence(**{**vars(span), "role": "acknowledgment"}))
            unacknowledged = []
        groups, context, _ = parse_utterance(text, phrases)
        if not groups and not is_acknowledgment(text) and len(_words(text)) >= UNDERSTOOD_MIN_WORDS:
            unknown = CandidateCall(flags=[FLAG_NOT_UNDERSTOOD], evidence=[span], excerpt=text)
            calls.append(unknown)
            unacknowledged.append(unknown)
            continue
        if is_acknowledgment(text):
            # An acknowledgment that repeats details ("Got it. Lane 5 and 6.") confirms, not adds.
            groups = [group for group in groups if group.lanes]
            for group in groups:
                for lane in group.lanes:
                    existing = _find_call(calls, group, lane)
                    if existing is not None:
                        existing.accepted = True
            continue
        phases, turn_number = _phases_and_turn(text)
        for group in groups:
            for lane in group.lanes or [None]:
                call = _find_call(calls, group, lane) or CandidateCall(lane=lane)
                if call not in calls:
                    calls.append(call)
                _fill_call(call, group, group_context, phases, turn_number, span, text)
                if call not in unacknowledged:
                    unacknowledged.append(call)
        for key in (KEY_EVENT, KEY_HEAT):
            group_context[key] = context[key] or group_context[key]
    for call in calls:
        _final_flags(call)
    return calls


def _find_call(calls: list[CandidateCall], group: _LaneGroup, lane: str | None) -> CandidateCall | None:
    """An earlier candidate for the same lane in the same group (a repeat or add-on)."""
    for call in calls:
        if lane is not None and call.lane == lane and (group.event in (None, call.event)) and (group.heat in (None, call.heat)):
            return call
    return None


def _fill_call(
    call: CandidateCall,
    group: _LaneGroup,
    group_context: dict[str, str | None],
    phases: list[str],
    turn_number: str | None,
    span: Evidence,
    text: str,
) -> None:
    """Copy what a lane group says into a candidate, noting anything inferred."""
    if group.event:
        call.event = group.event
    elif call.event is None and group_context[KEY_EVENT]:
        call.event = group_context[KEY_EVENT]
        call.flags.append(FLAG_EVENT_CARRIED)
    if group.heat:
        call.heat = group.heat
    elif call.heat is None and group_context[KEY_HEAT]:
        call.heat = group_context[KEY_HEAT]
        call.flags.append(FLAG_HEAT_CARRIED)
    if group.corrected:
        call.flags.append(FLAG_CORRECTED)
    for _, phrase, ratio in group.infractions:
        if phrase.description not in call.infractions:
            call.infractions.append(phrase.description)
        if phrase.stroke and phrase.stroke not in call.strokes:
            call.strokes.append(phrase.stroke)
        if ratio < 1.0:
            call.flags.append(FLAG_FUZZY)
    for phase in phases:
        if phase not in call.phases:
            call.phases.append(phase)
    call.turn_number = call.turn_number or turn_number
    if all(item.utterance_id != span.utterance_id for item in call.evidence):
        call.evidence.append(span)
        call.excerpt = (call.excerpt + " / " if call.excerpt else "") + text


def _final_flags(call: CandidateCall) -> None:
    """Add flags for anything still missing, without duplicates."""
    for missing, flag in ((call.event, FLAG_EVENT_MISSING), (call.heat, FLAG_HEAT_MISSING), (call.lane, FLAG_LANE_MISSING)):
        if missing is None:
            call.flags.append(flag)
    if not call.infractions:
        call.flags.append(FLAG_NO_INFRACTION)
    call.flags = list(dict.fromkeys(call.flags))
