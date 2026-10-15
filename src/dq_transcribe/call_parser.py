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

from dq_transcribe.slip_codes import rank_codes
from dq_transcribe.text_normalization import normalize_spoken_numbers, tokenize

PHRASES_PATH = Path(__file__).parent / "data" / "infraction_phrases.csv"
CODES_COLUMN = "codes_rev_2024_01"
ANY_STROKE = "*"
# Several codes for one stroke ("Backstroke=2B|2C|2D": a slip group such as "past vertical at turn").
CODE_ALTERNATIVES_SEPARATOR = "|"
# Stroke names as said on the radio (one or two words). Bare "fly", "back" and
# "breast" are not used: they appear inside other phrases ("towards the breast").
STROKE_WORDS = {
    ("butterfly",): "Butterfly", ("breaststroke",): "Breaststroke", ("breast", "stroke"): "Breaststroke",
    ("backstroke",): "Backstroke", ("back", "stroke"): "Backstroke", ("freestyle",): "Freestyle",
}

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
FLAG_CODE_NEEDS_STROKE = "slip code depends on the stroke"
FLAG_CODE_CHOICE = "several slip codes fit; pick one"
# An utterance this long with nothing recognized is still shown, so no call is lost.
UNDERSTOOD_MIN_WORDS = 4
FLAG_FUZZY = "infraction matched loosely"


@dataclass(frozen=True)
class InfractionPhrase:
    """A spoken phrase that names an infraction.

    Attributes:
        words: The phrase's words.
        description: Short description shown to the admin.
        stroke: The stroke this infraction belongs to, if only one.
        codes: DQ slip code(s) by stroke ("*" = any stroke), for the current slip
            revision; several codes are joined with "|".
    """

    words: tuple[str, ...]
    description: str
    stroke: str
    codes: dict[str, str] = field(default_factory=dict)


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
    codes: list[str | None] = field(default_factory=list)  # slip code per infraction, if it could be chosen
    code_options: list[list[str]] = field(default_factory=list)  # possible codes per infraction, likeliest first
    suggested_codes: list[str] = field(default_factory=list)  # slip lines matching the whole call's words
    stroke: str | None = None  # the stroke, if it could be worked out
    strokes: list[str] = field(default_factory=list)
    stroke_mentions: list[str] = field(default_factory=list)
    _code_maps: list[dict[str, str]] = field(default_factory=list, repr=False)
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
            "codes": self.codes, "code_options": self.code_options, "suggested_codes": self.suggested_codes,
            "stroke": self.stroke,
            "strokes": self.strokes, "phases": self.phases, "turn_number": self.turn_number,
            "accepted": self.accepted, "flags": self.flags, "excerpt": self.excerpt,
            "evidence": [vars(item) for item in self.evidence],
        }


def load_phrases(path: Path = PHRASES_PATH) -> list[InfractionPhrase]:
    """Read the spoken infraction phrases, longest first (so the most specific phrase wins)."""
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    phrases = [
        InfractionPhrase(
            tuple(_words(row["phrase"])), row["description"], row["stroke"] or "", _parse_codes(row.get(CODES_COLUMN) or "")
        )
        for row in rows
    ]
    return sorted(phrases, key=lambda phrase: -len(phrase.words))


def _parse_codes(text: str) -> dict[str, str]:
    """Read "Butterfly=1J;Breaststroke=3J" into a dictionary."""
    codes: dict[str, str] = {}
    for item in text.split(";"):
        if "=" in item:
            stroke, code = item.split("=", 1)
            codes[stroke.strip()] = code.strip()
    return codes


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


def find_infractions(
    words: list[str], phrases: list[InfractionPhrase]
) -> list[tuple[int, InfractionPhrase, float, int]]:
    """Find infraction phrases in a word list (exact or close matches, no overlaps).

    Returns:
        ``(word_index, phrase, similarity, word_count)`` for each match, in text order.
    """
    taken = [False] * len(words)
    matches: list[tuple[int, InfractionPhrase, float, int]] = []
    for phrase in phrases:
        size = len(phrase.words)
        target = " ".join(phrase.words)
        allow_fuzzy = len(target) >= FUZZY_MIN_PHRASE_CHARACTERS
        matcher = difflib.SequenceMatcher(None, "", target)  # target analysis is cached by set_seq1 reuse
        # Also try one extra word, so "shoulders were past vertical" matches "shoulders past vertical".
        for window_size in (size, size + 1) if allow_fuzzy else (size,):
            for start in range(0, len(words) - window_size + 1):
                if any(taken[start:start + window_size]):
                    continue
                window = " ".join(words[start:start + window_size])
                if window == target:
                    ratio = 1.0
                elif allow_fuzzy:
                    matcher.set_seq1(window)
                    # Cheap upper bounds first; the full ratio is only computed for likely matches.
                    if matcher.real_quick_ratio() < PHRASE_MATCH_MIN_RATIO or matcher.quick_ratio() < PHRASE_MATCH_MIN_RATIO:
                        continue
                    ratio = matcher.ratio()
                else:
                    continue
                if ratio >= PHRASE_MATCH_MIN_RATIO:
                    matches.append((start, phrase, ratio, window_size))
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
    infractions: list[tuple[int, InfractionPhrase, float, int]] = field(default_factory=list)
    stroke_mentions: list[str] = field(default_factory=list)


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
    def group_for(position: int) -> _LaneGroup:
        """The lane group that something said at ``position`` belongs to."""
        before = [group for group in groups if group.start <= position]
        target = before[-1] if before else (groups[0] if groups else None)
        if target is None:
            target = _LaneGroup(position, [], context[KEY_EVENT], context[KEY_HEAT])
            groups.append(target)
        return target

    for match in infraction_matches:
        group_for(match[0]).infractions.append(match)
    # Stroke names said outside infraction phrases ("butterfly kick" names a
    # breaststroke infraction, so its "butterfly" is not a stroke mention).
    inside_phrase = {position for start, _, _, length in infraction_matches for position in range(start, start + length)}
    for position in range(len(words)):
        for stroke_words, stroke in STROKE_WORDS.items():
            span = range(position, position + len(stroke_words))
            if tuple(words[position:position + len(stroke_words)]) == stroke_words and not inside_phrase.intersection(span):
                if groups:
                    target = group_for(position)
                    if stroke not in target.stroke_mentions:
                        target.stroke_mentions.append(stroke)
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
        _drop_general_infractions(call)
        choose_codes(call)
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
    for stroke in group.stroke_mentions:
        if stroke not in call.stroke_mentions:
            call.stroke_mentions.append(stroke)
    for _, phrase, ratio, _ in group.infractions:
        if phrase.description not in call.infractions:
            call.infractions.append(phrase.description)
            call._code_maps.append(phrase.codes)
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


def _drop_general_infractions(call: CandidateCall) -> None:
    """Keep only the specific infraction when both were heard.

    "Past vertical at turn, delayed initiating turn" names one infraction: the slip
    line "Past vertical at turn: delay initiating turn", not that and its group.
    """
    keep = [
        index for index, description in enumerate(call.infractions)
        if not any(other != description and other.startswith(description) for other in call.infractions)
    ]
    call.infractions = [call.infractions[index] for index in keep]
    call._code_maps = [call._code_maps[index] for index in keep]


def stroke_clues(call: CandidateCall) -> set[str]:
    """Strokes the call itself points to: a stroke named in it, or else infractions
    that exist in only one stroke (underwater recovery is butterfly)."""
    if len(set(call.stroke_mentions)) == 1:
        return set(call.stroke_mentions)
    return {next(iter(codes)) for codes in call._code_maps if len(codes) == 1 and ANY_STROKE not in codes}


def choose_codes(call: CandidateCall, event_stroke: str | None = None) -> None:
    """Work out the stroke and pick a DQ slip code for each infraction where possible.

    Args:
        call: The detected call (its codes and flags are updated).
        event_stroke: The stroke of the call's event if known from elsewhere (another
            call in the same event, a saved DQ, or later the Meet Manager file). Used
            only when the call itself gives no single stroke.
    """
    call.flags = [flag for flag in call.flags if flag not in (FLAG_CODE_NEEDS_STROKE, FLAG_CODE_CHOICE)]
    clues = stroke_clues(call)
    if len(clues) == 1:
        call.stroke = next(iter(clues))
    else:
        call.stroke = event_stroke if not clues else None
    call.codes, call.code_options = [], []
    needs_stroke = needs_choice = False
    for description, codes in zip(call.infractions, call._code_maps):
        by_stroke = {stroke: value.split(CODE_ALTERNATIVES_SEPARATOR) for stroke, value in codes.items()}
        every_code = list(dict.fromkeys(code for value in by_stroke.values() for code in value))
        if ANY_STROKE in by_stroke:
            fitting = by_stroke[ANY_STROKE]
        elif call.stroke is not None and call.stroke in by_stroke:
            fitting = by_stroke[call.stroke]
        elif len(by_stroke) == 1:
            fitting = next(iter(by_stroke.values()))
        else:
            fitting = every_code
            needs_stroke = len(every_code) > 1
        if not fitting:
            # The phrase list has no code for this: rank the slip's lines by its words.
            fitting = every_code = rank_codes(description, call.stroke)
        chosen = fitting[0] if len(fitting) == 1 else None
        needs_choice = needs_choice or (chosen is None and len(fitting) > 1 and not needs_stroke)
        call.codes.append(chosen)
        # Likeliest first: the codes that fit this call, then the other strokes' codes.
        call.code_options.append(list(dict.fromkeys(fitting + every_code)))
    call.suggested_codes = rank_codes(" ".join([call.excerpt, *call.infractions]), call.stroke)
    if needs_stroke:
        call.flags.append(FLAG_CODE_NEEDS_STROKE)
    elif needs_choice:
        call.flags.append(FLAG_CODE_CHOICE)


def _final_flags(call: CandidateCall) -> None:
    """Add flags for anything still missing, without duplicates."""
    for missing, flag in ((call.event, FLAG_EVENT_MISSING), (call.heat, FLAG_HEAT_MISSING), (call.lane, FLAG_LANE_MISSING)):
        if missing is None:
            call.flags.append(flag)
    if not call.infractions:
        call.flags.append(FLAG_NO_INFRACTION)
    call.flags = list(dict.fromkeys(call.flags))
