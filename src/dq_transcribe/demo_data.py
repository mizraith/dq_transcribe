"""Training meet: a made-up meet in progress, with DQs in every stage.

Shipped with the app so officials can practise the whole DQ workflow before a
real meet. The app creates it on its first start (``ensure_demo_meet``); the
Meet setup page can rebuild it with fresh times ("Rebuild training meet"). From
a terminal:

    PYTHONPATH=src python -m dq_transcribe.demo_data            # create it if missing
    PYTHONPATH=src python -m dq_transcribe.demo_data --replace  # rebuild it now

The meet "Workflow demo (test data)" (it never touches other meets and does not
change which meet is active) has:

* a meet program of 25 events (all strokes, two relays) with made-up swimmers
  and clubs, so swimmer and club fill in and each event has a stroke;
* 4 to 10 DQs per event, each with a short silent clip already "transcribed"
  as the radio call (and usually an "Accepted."), so every DQ has "Heard in"
  audio and the transcript shows which lines are DQs;
* the meet as it would look about two hours in. Events swim in number order,
  about 3 minutes apart, and close in order: the early events are notified
  (some protested, upheld or overturned; a few declined), the protest windows
  of the last notified events are still open, the next events are ready to
  notify, then events waiting on incomplete or called DQs, and the last events
  have just been called.

The DQs are generated from a fixed seed, so every rebuild looks the same apart
from the times. Pick the training meet in the Meet picker to use it; pick the
real meet again before recording.
"""

from __future__ import annotations

import argparse
import io
import json
import random
import wave
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dq_transcribe import constants
from dq_transcribe.database import Database
from dq_transcribe.dq_store import DqStore
from dq_transcribe.meet_files.model import MeetProgram, ProgramEntry, ProgramEvent
from dq_transcribe.meet_files.store import MeetProgramStore

DEMO_MEET_NAME = "Workflow demo (test data)"
DEMO_SOURCE = "training meet (made-up data)"
DEMO_NOTE = "Training data (made up)."
RANDOM_SEED = 2026
CLIP_SECONDS = 4.0
MINUTES_BETWEEN_EVENTS = 3
MINUTES_BEFORE_NOTIFYING = 4  # after its race, an event is closed and notified this much later
DQS_PER_EVENT = (4, 10)
LANES = 8
# Event number -> stage of the meet when the training data is built (events close in number order).
LAST_NOTIFIED_EVENT = 19
LAST_READY_EVENT = 21
LAST_WAITING_EVENT = 23  # after this: just called
EVENTS = (
    "Girls 10 & Under 50 Yard Freestyle", "Boys 10 & Under 50 Yard Freestyle",
    "Girls 11-12 100 Yard Breaststroke", "Boys 11-12 100 Yard Breaststroke",
    "Girls 13 & Over 200 Yard Individual Medley", "Boys 13 & Over 200 Yard Individual Medley",
    "Girls 10 & Under 50 Yard Backstroke", "Boys 10 & Under 50 Yard Backstroke",
    "Girls 11-12 100 Yard Butterfly", "Boys 11-12 100 Yard Butterfly",
    "Mixed 10 & Under 200 Yard Freestyle Relay",
    "Girls 13 & Over 100 Yard Breaststroke", "Boys 13 & Over 100 Yard Breaststroke",
    "Girls 10 & Under 50 Yard Breaststroke", "Boys 10 & Under 50 Yard Breaststroke",
    "Girls 11-12 100 Yard Backstroke", "Boys 11-12 100 Yard Backstroke",
    "Girls 13 & Over 100 Yard Butterfly", "Boys 13 & Over 100 Yard Butterfly",
    "Girls 10 & Under 100 Yard Individual Medley", "Boys 10 & Under 100 Yard Individual Medley",
    "Girls 11-12 50 Yard Freestyle", "Boys 11-12 50 Yard Freestyle",
    "Girls 10 & Under 50 Yard Butterfly", "Mixed 11-12 200 Yard Medley Relay",
)
FIRST_NAMES = ("Avery", "Blake", "Casey", "Drew", "Emery", "Finley", "Harper", "Jordan", "Kai", "Logan", "Morgan",
               "Parker", "Quinn", "Riley", "Skyler", "Taylor", "Rowan", "Sage", "Reese", "Dakota")
LAST_NAMES = ("Demo", "Sample", "Example", "Testa", "Mock", "Placeholder", "Fakename", "Trainee")
CLUBS = ("AAA", "BBB", "CCC", "DDD", "EEE")
RELAY_LETTERS = ("A", "B")
OFFICIALS = (
    ("Pat Judge", "Stroke & Turn Judge"), ("Chris Judge", "Stroke & Turn Judge"), ("Robin Judge", "Stroke & Turn Judge"),
    ("Lee Chief", "Chief Judge"), ("Sam Deckref", "Deck Referee"), ("Jo Meetref", "Meet Referee"), ("Ari Admin", "Admin Official"),
)
JUDGES = [name for name, role in OFFICIALS if role == "Stroke & Turn Judge"]
CHIEF_JUDGE, DECK_REFEREE, MEET_REFEREE = "Lee Chief", "Sam Deckref", "Jo Meetref"
NOTIFIED_BY = ("Chief Judge", "Admin Official", "Printed slip")


@dataclass(frozen=True)
class Infraction:
    """A way to be disqualified: what the official says, and how the slip records it."""

    spoken: str
    description: str
    code: str
    phase: str
    detail_kind: str = ""  # "turn" (turn number) or "swimmer" (relay swimmer number)


INFRACTIONS = {
    constants.STROKE_FREESTYLE: (
        Infraction("no touch at the turn", "No touch at turn", "4A", "Turn", "turn"),
        Infraction("head did not break the surface by 15 meters", "Head did not break surface by 15m", "4B", "Start"),
        Infraction("re-submerged", "Re-submerged", "4C", "Swim"),
        Infraction("false start", "False start", "7A", "Start"),
    ),
    constants.STROKE_BACKSTROKE: (
        Infraction("no touch at the turn", "No touch at turn", "2A", "Turn", "turn"),
        Infraction("past vertical at the turn, delayed initiating turn", "Past vertical at turn: delay initiating turn", "2C", "Turn"),
        Infraction("past vertical at the turn, multiple strokes", "Past vertical at turn: multiple strokes", "2D", "Turn"),
        Infraction("shoulders past vertical towards the breast", "Shoulders past vertical towards the breast", "2L", "Finish"),
        Infraction("not on back off the wall", "Not on back off wall", "2H", "Turn"),
    ),
    constants.STROKE_BREASTSTROKE: (
        Infraction("one hand touch", "One hand touch", "3J", "Finish"),
        Infraction("scissors kick", "Kick: scissors", "3C", "Swim"),
        Infraction("alternating kick", "Kick: alternating", "3A", "Swim"),
        Infraction("arms past the hipline", "Arms: past hipline", "3D", "Swim"),
        Infraction("double pulls", "Cycle: double pulls/kicks", "3S", "Turn"),
        Infraction("hands not separated at the touch", "Touch: not separated", "3K", "Turn"),
    ),
    constants.STROKE_BUTTERFLY: (
        Infraction("alternating kick", "Kick: alternating", "1A", "Swim"),
        Infraction("breaststroke kick", "Kick: breast", "1B", "Swim"),
        Infraction("one hand touch", "One hand touch", "1J", "Finish"),
        Infraction("underwater recovery", "Arms: underwater recovery", "1F", "Swim"),
        Infraction("non simultaneous touch", "Touch: non-simultaneous", "1L", "Turn"),
    ),
    constants.STROKE_INDIVIDUAL_MEDLEY: (
        Infraction("out of sequence", "IM: out of sequence", "5B", "Swim"),
        Infraction("on the breaststroke, one hand touch", "IM stroke infraction: breaststroke one hand touch", "5A", "Turn"),
        Infraction("on the butterfly, alternating kick", "IM stroke infraction: butterfly alternating kick", "5A", "Swim"),
    ),
    constants.STROKE_FREESTYLE_RELAY: (
        Infraction("early take off", "Relay: early take-off", "6F-H", "Start", "swimmer"),
    ),
    constants.STROKE_MEDLEY_RELAY: (
        Infraction("early take off", "Relay: early take-off", "6F-H", "Start", "swimmer"),
        Infraction("changed order", "Relay: changed order", "6L", "Swim"),
    ),
}
ACKNOWLEDGMENTS = ("Accepted.", "Got it, accepted.", "Copy, accepted.", "Accepted, thank you.")


def demo_program(randomizer: random.Random) -> tuple[MeetProgram, dict[str, int]]:
    """The made-up meet program, and the number of heats of each event."""
    program = MeetProgram(meet_name=DEMO_MEET_NAME)
    heats_by_event: dict[str, int] = {}
    for index, description in enumerate(EVENTS, start=1):
        number = str(index)
        event = ProgramEvent.from_description(number, description)
        program.events.append(event)
        heats = randomizer.randint(3, 6)
        heats_by_event[number] = heats
        for heat in range(1, heats + 1):
            for lane in range(1, LANES + 1):
                club = CLUBS[(index + heat + lane) % len(CLUBS)]
                if event.relay:
                    swimmer = f"{club}-{RELAY_LETTERS[(heat + lane) % len(RELAY_LETTERS)]}"
                else:
                    swimmer = f"{randomizer.choice(FIRST_NAMES)} {randomizer.choice(LAST_NAMES)}"
                program.entries.append(ProgramEntry(event_number=number, heat=str(heat), lane=str(lane),
                                                    swimmer=swimmer, club=club, relay=event.relay))
    return program, heats_by_event


def silent_wav(seconds: float) -> bytes:
    """A short silent clip (16 kHz mono 16-bit), so "Heard in" has audio to play."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(constants.AUDIO_CHANNEL_COUNT)
        writer.setsampwidth(constants.WAV_SAMPLE_WIDTH_BYTES)
        writer.setframerate(constants.AUDIO_SAMPLE_RATE_HZ)
        writer.writeframes(b"\x00\x00" * int(seconds * constants.AUDIO_SAMPLE_RATE_HZ))
    return buffer.getvalue()


def find_demo_meet(database: Database) -> int | None:
    """The training meet's id, or None if it does not exist."""
    meet = next((meet for meet in database.list_meets() if meet["name"] == DEMO_MEET_NAME), None)
    return None if meet is None else int(meet["id"])


def _remove_demo_contents(database: Database, meet_id: int, recordings_directory: Path) -> None:
    """Delete the training meet's DQs, clips (and their audio) and meet file versions. Only this meet."""
    with database.transaction() as connection:
        dq_ids = [row["id"] for row in connection.execute("SELECT id FROM dqs WHERE meet_id = ?", (meet_id,))]
        for dq_id in dq_ids:
            for table in ("dq_infractions", "dq_evidence", "dq_history"):
                connection.execute(f"DELETE FROM {table} WHERE dq_id = ?", (dq_id,))
        connection.execute("DELETE FROM dqs WHERE meet_id = ?", (meet_id,))
        clips = connection.execute("SELECT id, audio_filename FROM clips WHERE meet_id = ?", (meet_id,)).fetchall()
        for clip in clips:
            connection.execute("DELETE FROM utterances WHERE clip_id = ?", (clip["id"],))
            (recordings_directory / clip["audio_filename"]).unlink(missing_ok=True)
        connection.execute("DELETE FROM clips WHERE meet_id = ?", (meet_id,))
        for row in connection.execute("SELECT id FROM meet_files WHERE meet_id = ?", (meet_id,)).fetchall():
            for table in ("meet_program_events", "meet_program_entries", "meet_program_sessions"):
                connection.execute(f"DELETE FROM {table} WHERE file_id = ?", (row["id"],))
        connection.execute("DELETE FROM meet_files WHERE meet_id = ?", (meet_id,))


def _detail(infraction: Infraction, randomizer: random.Random) -> tuple[str, str]:
    """The slip detail ("3" for the 3rd turn, "2" for the 2nd relay swimmer) and how it is said."""
    if infraction.detail_kind == "turn":
        turn = randomizer.randint(1, 3)
        return str(turn), f", turn {turn}"
    if infraction.detail_kind == "swimmer":
        swimmer = randomizer.randint(2, 4)
        return str(swimmer), f", swimmer {swimmer}"
    return "", ""


def create_demo_meet(database: Database, recordings_directory: Path, replace: bool = False, now: datetime | None = None) -> int:
    """Create (or rebuild) the training meet and its DQs.

    Args:
        database: The app database (already initialized).
        recordings_directory: Where clip audio is stored.
        replace: Rebuild the training meet if it already exists.
        now: The time the meet is "at" (default: now).

    Returns:
        The training meet's id.
    """
    from dq_transcribe.server import meet_folder_name  # local import: the server imports this module

    now = now or datetime.now(timezone.utc)
    randomizer = random.Random(RANDOM_SEED)
    programs = MeetProgramStore(database)
    programs.initialize()
    store = DqStore(database, programs)
    store.initialize()
    meet_id = find_demo_meet(database)
    if meet_id is not None and not replace:
        return meet_id
    if meet_id is not None:
        _remove_demo_contents(database, meet_id, recordings_directory)
    else:
        active_meet_id = database.get_active_meet_id()
        meet_id = database.create_meet(DEMO_MEET_NAME, now.astimezone().date().isoformat())
        database.set_active_meet(active_meet_id)  # creating a meet makes it active: put the real one back
    meet = database.get_meet(meet_id)
    database.update_meet(meet_id, DEMO_MEET_NAME, meet["start_date"], list(OFFICIALS))
    program, heats_by_event = demo_program(randomizer)
    programs.save(meet_id, program, constants.MEET_FILE_FORMAT_TEXT, DEMO_SOURCE, DEMO_SOURCE)
    events = {event.number: event for event in program.events}

    folder = recordings_directory / meet_folder_name(meet) / now.astimezone().strftime(constants.DAY_DIRECTORY_FORMAT)
    folder.mkdir(parents=True, exist_ok=True)
    audio = silent_wav(CLIP_SECONDS)
    last_event = len(EVENTS)
    clip_number = 0
    for number in range(1, last_event + 1):
        event = events[str(number)]
        race_time = now - timedelta(minutes=(last_event - number) * MINUTES_BETWEEN_EVENTS + 2)
        dq_count = randomizer.randint(*DQS_PER_EVENT)
        heats = heats_by_event[str(number)]
        spots = randomizer.sample([(heat, lane) for heat in range(1, heats + 1) for lane in range(1, LANES + 1)], dq_count)
        spots.sort()
        declined_index = randomizer.randrange(dq_count) if randomizer.random() < 0.35 else None
        for position, (heat, lane) in enumerate(spots):
            infraction = randomizer.choice(INFRACTIONS[event.stroke])
            detail, detail_spoken = _detail(infraction, randomizer)
            called_at = race_time + timedelta(seconds=20 + 15 * position)
            said = f"Event {number}, heat {heat}, lane {lane}, {infraction.spoken}{detail_spoken}."
            clip_number += 1
            audio_path = folder / f"training_clip_{clip_number:03d}.wav"
            audio_path.write_bytes(audio)
            acknowledged = number < last_event or position % 2 == 0
            with database.transaction() as connection:
                clip_id = connection.execute(
                    "INSERT INTO clips (created_at, started_at, ended_at, audio_filename, status, duration_seconds, refine_status, meet_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (called_at.isoformat(timespec="seconds"), called_at.isoformat(timespec="seconds"),
                     (called_at + timedelta(seconds=CLIP_SECONDS)).isoformat(timespec="seconds"),
                     audio_path.relative_to(recordings_directory).as_posix(), constants.CLIP_STATUS_DONE, CLIP_SECONDS,
                     constants.CLIP_STATUS_DONE, meet_id),
                ).lastrowid
                utterance_id = connection.execute(
                    "INSERT INTO utterances (clip_id, position, start_seconds, end_seconds, text, original_text) VALUES (?, 0, 0, 2.5, ?, ?)",
                    (clip_id, said, said),
                ).lastrowid
                if acknowledged:
                    ack = randomizer.choice(ACKNOWLEDGMENTS)
                    connection.execute(
                        "INSERT INTO utterances (clip_id, position, start_seconds, end_seconds, text, original_text) VALUES (?, 1, 2.8, 3.8, ?, ?)",
                        (clip_id, ack, ack),
                    )

            # Where this event is in the meet decides what the admin has done with it so far.
            incomplete = number > LAST_READY_EVENT and number <= LAST_WAITING_EVENT and position % 3 == 1
            just_called = number > LAST_WAITING_EVENT and not acknowledged
            payload = {
                "event": str(number), "heat": str(heat), "lane": str(lane), "accepted": not just_called,
                "official": None if incomplete or just_called else JUDGES[(number + position) % len(JUDGES)],
                "official_role": "Stroke & Turn Judge", "chief_judge": CHIEF_JUDGE,
                "referee": None if just_called or number > LAST_WAITING_EVENT else DECK_REFEREE,
                "relay_leg": detail if infraction.detail_kind == "swimmer" else None,
                "notes": DEMO_NOTE,
                constants.REQUEST_KEY_CANDIDATE_KEY: f"{utterance_id}:{lane}",
                "infractions": [{"description": infraction.description, "code": infraction.code,
                                 "phases": [infraction.phase], "detail": detail if infraction.detail_kind == "turn" else ""}],
                "evidence": [{"clip_id": clip_id, "utterance_id": utterance_id, "start_seconds": 0.0, "end_seconds": 2.5,
                              "role": constants.EVIDENCE_ROLE_CALL}],
            }
            dq_id = store.create_dq(payload, meet_id)
            if position == declined_index and number <= LAST_WAITING_EVENT:
                store.change_state(dq_id, constants.DQ_STATE_DECLINED, DECK_REFEREE, note="Not clear enough: benefit of the doubt to the swimmer",
                                   at=(called_at + timedelta(minutes=2)).isoformat())
                continue
            if number <= LAST_NOTIFIED_EVENT:
                notified_at = race_time + timedelta(minutes=MINUTES_BEFORE_NOTIFYING)
                store.change_state(dq_id, constants.DQ_STATE_NOTIFIED, NOTIFIED_BY[number % len(NOTIFIED_BY)], at=notified_at.isoformat())
                roll = randomizer.random()
                if number == LAST_NOTIFIED_EVENT and position == 0:
                    # One protest still waiting for the referee's ruling, inside its window.
                    store.change_state(dq_id, constants.DQ_STATE_PROTESTED, note="Coach protested (training data)",
                                       at=(notified_at + timedelta(minutes=3)).isoformat())
                elif roll < 0.08:
                    protested_at = notified_at + timedelta(minutes=randomizer.randint(3, 15))
                    if protested_at < now:
                        store.change_state(dq_id, constants.DQ_STATE_PROTESTED, note="Coach protested (training data)", at=protested_at.isoformat())
                        ruled_at = protested_at + timedelta(minutes=6)
                        if ruled_at < now:
                            ruling = constants.DQ_STATE_UPHELD if roll < 0.06 else constants.DQ_STATE_OVERTURNED
                            store.change_state(dq_id, ruling, DECK_REFEREE, at=ruled_at.isoformat())
    statuses = {status: sum(1 for dq in store.list_dqs(meet_id) if dq["status"] == status) for status in constants.DQ_STATUS_LABELS}
    print(f"Training meet {meet_id} ready: {sum(statuses.values())} DQs in {last_event} events {json.dumps(statuses)}.")
    return meet_id


def ensure_demo_meet(database: Database, recordings_directory: Path) -> int:
    """Create the training meet if it does not exist yet (called when the app starts)."""
    return create_demo_meet(database, recordings_directory, replace=False)


def main() -> None:
    """Command line: create (or with --replace, rebuild) the training meet in the app's database."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--replace", action="store_true", help="rebuild the training meet now (fresh times)")
    arguments = parser.parse_args()
    database = Database(constants.DATABASE_PATH)
    database.initialize()
    create_demo_meet(database, constants.RECORDINGS_DIRECTORY, replace=arguments.replace)


if __name__ == "__main__":
    main()
