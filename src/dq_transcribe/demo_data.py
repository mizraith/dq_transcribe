"""Demo data: a separate meet with DQs in every stage, to try the whole workflow.

Run on the tablet (the app may keep running):

    PYTHONPATH=src python -m dq_transcribe.demo_data            # create the demo meet
    PYTHONPATH=src python -m dq_transcribe.demo_data --replace  # rebuild it from scratch

It creates the meet "Workflow demo (test data)" (it never touches other meets
and does not change which meet is active), with:

* a small meet program (6 events, made-up swimmers and clubs), so swimmer and
  club fill in and each event has a stroke;
* one short silent clip per radio call, transcribed already, so every DQ has
  "Heard in" audio, transcript lines show their DQ, and the protest window
  runs from the call time;
* DQs in every stage: an event ready to notify, events waiting on called or
  incomplete DQs, notified DQs with the protest window open and closed, a
  protested DQ, and a declined one.

Pick the demo meet in the Meet picker to use it; pick your real meet again
before recording.
"""

from __future__ import annotations

import argparse
import io
import json
import wave
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dq_transcribe import constants
from dq_transcribe.database import Database
from dq_transcribe.dq_store import DqStore
from dq_transcribe.meet_files.model import MeetProgram, ProgramEntry, ProgramEvent
from dq_transcribe.meet_files.store import MeetProgramStore
from dq_transcribe.server import meet_folder_name

DEMO_MEET_NAME = "Workflow demo (test data)"
DEMO_SOURCE = "demo data (made up)"
CLIP_SECONDS = 4.0
EVENTS = (
    ("1", "Girls 10 & Under 50 Yard Freestyle"),
    ("2", "Boys 10 & Under 50 Yard Breaststroke"),
    ("3", "Girls 11-12 100 Yard Butterfly"),
    ("4", "Boys 11-12 100 Yard Backstroke"),
    ("5", "Girls 13 & Over 200 Yard IM"),
    ("6", "Boys 13 & Over 100 Yard Breaststroke"),
)
HEATS = 3
LANES = 6
FIRST_NAMES = ("Avery", "Blake", "Casey", "Drew", "Emery", "Finley", "Harper", "Jordan", "Kai", "Logan", "Morgan", "Parker", "Quinn", "Riley", "Skyler", "Taylor")
LAST_NAMES = ("Demo", "Sample", "Example", "Testa", "Mock", "Placeholder")
CLUBS = ("AAA", "BBB", "CCC", "DDD")
OFFICIALS = (("Pat Judge", "Stroke & Turn Judge"), ("Lee Chief", "Chief Judge"), ("Sam Deckref", "Deck Referee"),
             ("Jo Meetref", "Meet Referee"), ("Ari Admin", "Admin Official"))

# (minutes ago, event, heat, lane, what was said, infraction, code, phase, detail, stage, missing official?)
CALLS = (
    (24, "2", "1", "3", "Possible DQ, event 2, heat 1, lane 3, one hand touch.", "One hand touch", "3J", "Finish", "", "accepted", False),
    (22, "2", "2", "5", "Event 2, heat 2, lane 5, scissors kick.", "Kick: scissors", "3C", "Swim", "", "accepted", False),
    (16, "3", "1", "2", "Event 3, heat 1, lane 2, alternating kick.", "Kick: alternating", "1A", "Swim", "", "accepted", False),
    (14, "3", "1", "4", "Event 3, heat 1, lane 4, I think a non simultaneous touch.", "Touch: non-simultaneous", "1L", "Turn", "", "called", False),
    (12, "4", "2", "1", "Event 4, heat 2, lane 1, past vertical at the turn, delayed initiating turn.", "Past vertical at turn: delay initiating turn", "2C", "Turn", "", "notified", False),
    (11, "4", "2", "6", "Event 4, heat 2, lane 6, no touch at turn, third turn.", "No touch at turn", "2A", "Turn", "3", "protested", False),
    (55, "5", "1", "5", "Event 5, heat 1, lane 5, out of sequence.", "IM: out of sequence", "5B", "Swim", "", "notified", False),
    (6, "6", "1", "4", "Event 6, heat 1, lane 4, double pulls.", "Cycle: double pulls/kicks", "3S", "Swim", "", "accepted", True),
    (40, "1", "3", "2", "Event 1, heat 3, lane 2, did not finish. Actually never mind, scratch that.", "Did not finish", "7C", "Finish", "", "declined", False),
)


def demo_program() -> MeetProgram:
    """A made-up meet program: every heat and lane of every event has a swimmer."""
    program = MeetProgram(meet_name=DEMO_MEET_NAME)
    for number, description in EVENTS:
        program.events.append(ProgramEvent.from_description(number, description))
        for heat in range(1, HEATS + 1):
            for lane in range(1, LANES + 1):
                index = int(number) * 31 + heat * 7 + lane
                program.entries.append(ProgramEntry(
                    event_number=number, heat=str(heat), lane=str(lane),
                    swimmer=f"{FIRST_NAMES[index % len(FIRST_NAMES)]} {LAST_NAMES[index % len(LAST_NAMES)]}",
                    club=CLUBS[index % len(CLUBS)],
                ))
    return program


def silent_wav(seconds: float) -> bytes:
    """A short silent clip (16 kHz mono 16-bit), so "Heard in" has audio to play."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(constants.AUDIO_CHANNEL_COUNT)
        writer.setsampwidth(constants.WAV_SAMPLE_WIDTH_BYTES)
        writer.setframerate(constants.AUDIO_SAMPLE_RATE_HZ)
        writer.writeframes(b"\x00\x00" * int(seconds * constants.AUDIO_SAMPLE_RATE_HZ))
    return buffer.getvalue()


def _remove_demo_meet(database: Database, meet_id: int, recordings_directory: Path) -> None:
    """Delete the demo meet's DQs, clips (and their audio) and meet file versions. Only this meet."""
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


def create_demo_meet(database: Database, recordings_directory: Path, replace: bool = False, now: datetime | None = None) -> int:
    """Create (or rebuild) the demo meet and its DQs.

    Args:
        database: The app database (already initialized).
        recordings_directory: Where clip audio is stored.
        replace: Rebuild the demo meet if it already exists.
        now: The time to count "minutes ago" from (default: now).

    Returns:
        The demo meet's id.
    """
    now = now or datetime.now(timezone.utc)
    programs = MeetProgramStore(database)
    programs.initialize()
    store = DqStore(database, programs)
    store.initialize()
    existing = next((meet for meet in database.list_meets() if meet["name"] == DEMO_MEET_NAME), None)
    if existing is not None:
        if not replace:
            print(f"The demo meet already exists (id {existing['id']}). Use --replace to rebuild it.")
            return int(existing["id"])
        _remove_demo_meet(database, int(existing["id"]), recordings_directory)
        meet_id = int(existing["id"])
    else:
        active_meet_id = database.get_active_meet_id()
        meet_id = database.create_meet(DEMO_MEET_NAME, now.astimezone().date().isoformat())
        database.set_active_meet(active_meet_id)  # creating a meet makes it active: put the real one back
    meet = database.get_meet(meet_id)
    database.update_meet(meet_id, DEMO_MEET_NAME, meet["start_date"], list(OFFICIALS))
    programs.save(meet_id, demo_program(), constants.MEET_FILE_FORMAT_TEXT, DEMO_SOURCE, DEMO_SOURCE)

    folder = recordings_directory / meet_folder_name(meet) / now.astimezone().strftime(constants.DAY_DIRECTORY_FORMAT)
    folder.mkdir(parents=True, exist_ok=True)
    audio = silent_wav(CLIP_SECONDS)
    for index, (minutes_ago, event, heat, lane, said, infraction, code, phase, detail, stage, missing_official) in enumerate(CALLS):
        started = now - timedelta(minutes=minutes_ago)
        audio_path = folder / f"demo_clip_{index + 1:02d}.wav"
        audio_path.write_bytes(audio)
        with database.transaction() as connection:
            clip_id = connection.execute(
                "INSERT INTO clips (created_at, started_at, ended_at, audio_filename, status, duration_seconds, refine_status, meet_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (started.isoformat(timespec="seconds"), started.isoformat(timespec="seconds"),
                 (started + timedelta(seconds=CLIP_SECONDS)).isoformat(timespec="seconds"),
                 audio_path.relative_to(recordings_directory).as_posix(), constants.CLIP_STATUS_DONE, CLIP_SECONDS,
                 constants.CLIP_STATUS_DONE, meet_id),
            ).lastrowid
            utterance_id = connection.execute(
                "INSERT INTO utterances (clip_id, position, start_seconds, end_seconds, text, original_text) VALUES (?, 0, 0, ?, ?, ?)",
                (clip_id, CLIP_SECONDS, said, said),
            ).lastrowid
        payload = {
            "event": event, "heat": heat, "lane": lane, "accepted": stage != "called",
            "official": None if missing_official else OFFICIALS[0][0], "official_role": OFFICIALS[0][1],
            "chief_judge": OFFICIALS[1][0], "referee": OFFICIALS[2][0], "notes": "Demo data (made up).",
            constants.REQUEST_KEY_CANDIDATE_KEY: f"{utterance_id}:{lane}",
            "infractions": [{"description": infraction, "code": code, "phases": [phase], "detail": detail}],
            "evidence": [{"clip_id": clip_id, "utterance_id": utterance_id, "start_seconds": 0.0,
                          "end_seconds": CLIP_SECONDS, "role": constants.EVIDENCE_ROLE_CALL}],
        }
        dq_id = store.create_dq(payload, meet_id)
        notified_at = started + timedelta(minutes=3)
        if stage in ("notified", "protested"):
            store.change_state(dq_id, constants.DQ_STATE_NOTIFIED, "Chief Judge", at=notified_at.isoformat())
        if stage == "protested":
            store.change_state(dq_id, constants.DQ_STATE_PROTESTED, note="Demo protest",
                               at=(started + timedelta(minutes=8)).isoformat())
        if stage == "declined":
            store.change_state(dq_id, constants.DQ_STATE_DECLINED, "Deck Referee", note="Caller withdrew it")
    counts = json.dumps({status: sum(1 for dq in store.list_dqs(meet_id) if dq["status"] == status)
                         for status in constants.DQ_STATUS_LABELS})
    print(f"Demo meet {meet_id} ready: {len(CALLS)} DQs {counts}. Pick '{DEMO_MEET_NAME}' in the Meet picker to use it.")
    return meet_id


def main() -> None:
    """Command line: create or rebuild the demo meet in the app's database."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--replace", action="store_true", help="rebuild the demo meet from scratch")
    arguments = parser.parse_args()
    database = Database(constants.DATABASE_PATH)
    database.initialize()
    create_demo_meet(database, constants.RECORDINGS_DIRECTORY, replace=arguments.replace)


if __name__ == "__main__":
    main()
