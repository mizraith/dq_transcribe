"""Demo meet: a separate database filled with made-up officials.

Lets anyone try the whole workflow (the sign-in list and admin exceptions, Teams,
printouts, the roster) without touching the real meet. The demo lives in its own
SQLite file (``constants.DEMO_DATABASE_PATH``) and is rebuilt from scratch every
time a demo is started or reset.

The size is set per session (``DemoSize``): how many stroke & turn judges and
trainees sign in to each session, plus, when ticked, the corner officials and the
admin in every session. People are shared between sessions, as at a real meet: a
session with fewer judges than another gets a random selection of the same crew.

Names are invented from short first/last-name lists; clubs use made-up codes
(``DMOA``...) so nothing looks like a real person or club.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from officials_signin import constants
from officials_signin.database import Database, Validation, not_checked_validation

_SQLITE_SIDE_FILE_SUFFIXES = ("-wal", "-shm")


@dataclass(frozen=True)
class SessionSize:
    """How many stroke & turn officials sign in to one demo session.

    Attributes:
        judges: Certified stroke & turn judges.
        trainees: Stroke & turn trainees (they shadow a mentor).
    """

    judges: int
    trainees: int


@dataclass(frozen=True)
class DemoSize:
    """The size of a demo meet.

    Attributes:
        sessions: One ``SessionSize`` per session, in order (1 to
            ``constants.DEMO_MAX_SESSIONS``).
        corner_officials: Also sign in the corner officials and the admin
            (``constants.DEMO_SPECIAL_ROLES``) to every session.
    """

    sessions: tuple[SessionSize, ...]
    corner_officials: bool

    def to_payload(self) -> dict[str, Any]:
        """The size in the shape the demo page sends (also stored for "Reset demo")."""
        return {
            constants.KEY_SESSIONS: [
                {constants.KEY_JUDGES_COUNT: size.judges, constants.KEY_TRAINEES_COUNT: size.trainees}
                for size in self.sessions
            ],
            constants.KEY_CORNER_OFFICIALS: self.corner_officials,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> DemoSize:
        """Read and check a size sent by the demo page (or stored).

        Raises:
            ValueError: With a message for the admin when a number is out of range.
        """
        rows = payload.get(constants.KEY_SESSIONS)
        if not isinstance(rows, list) or not 1 <= len(rows) <= constants.DEMO_MAX_SESSIONS:
            raise ValueError(f"Sessions must be 1 to {constants.DEMO_MAX_SESSIONS}")
        sizes = []
        for number, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                raise ValueError(f"Session {number}: expected numbers")
            judges = row.get(constants.KEY_JUDGES_COUNT)
            trainees = row.get(constants.KEY_TRAINEES_COUNT)
            if isinstance(judges, bool) or not isinstance(judges, int) or not 0 <= judges <= constants.DEMO_MAX_JUDGES:
                raise ValueError(f"Session {number}: judges must be 0 to {constants.DEMO_MAX_JUDGES}")
            if isinstance(trainees, bool) or not isinstance(trainees, int) or not 0 <= trainees <= constants.DEMO_MAX_TRAINEES:
                raise ValueError(f"Session {number}: trainees must be 0 to {constants.DEMO_MAX_TRAINEES}")
            sizes.append(SessionSize(judges, trainees))
        return cls(tuple(sizes), bool(payload.get(constants.KEY_CORNER_OFFICIALS, True)))


def default_demo_size() -> DemoSize:
    """The demo size used when none has been chosen yet."""
    return DemoSize(
        tuple(
            SessionSize(constants.DEMO_DEFAULT_JUDGES, constants.DEMO_DEFAULT_TRAINEES)
            for _ in range(constants.DEMO_DEFAULT_SESSIONS)
        ),
        corner_officials=True,
    )


def fake_names(count: int, generator: random.Random) -> list[str]:
    """``count`` different made-up names, a few with a quoted nickname.

    Args:
        count: How many names.
        generator: Random source (seed it for repeatable demos and tests).

    Returns:
        Names like ``Avery Abbott`` or ``Blake "Ace" Barnes``.
    """
    pairs = [(first, last) for first in constants.DEMO_FIRST_NAMES for last in constants.DEMO_LAST_NAMES]
    generator.shuffle(pairs)
    names = []
    for first, last in pairs[:count]:
        if generator.random() < constants.DEMO_NICKNAME_SHARE:
            names.append(f'{first} "{generator.choice(constants.DEMO_NICKNAMES)}" {last}')
        else:
            names.append(f"{first} {last}")
    return names


def demo_years(generator: random.Random, head_official: bool) -> int:
    """Years certified for a made-up official (see ``constants.DEMO_YEARS_WEIGHTS``).

    Args:
        generator: Random source.
        head_official: A corner official or the admin: at least
            ``constants.DEMO_HEAD_OFFICIAL_MIN_YEARS``.

    Returns:
        1 to 15, mostly 1-3 for stroke & turn judges.
    """
    choices = [
        (years, weight) for years, weight in constants.DEMO_YEARS_WEIGHTS.items()
        if not head_official or years >= constants.DEMO_HEAD_OFFICIAL_MIN_YEARS
    ]
    return generator.choices([years for years, _ in choices], weights=[weight for _, weight in choices])[0]


def session_name(session_date: date, session_type: str) -> str:
    """``Friday PM``, ``Saturday Prelims`` (same style as Meet setup's suggestion)."""
    return f"{session_date.strftime('%A')} {session_type}"


def planned_session_names(first_day: date) -> list[str]:
    """Names of the sessions a demo starting on ``first_day`` can have, in order."""
    return [
        session_name(first_day + timedelta(days=day_offset), session_type)
        for day_offset, session_type, _ in constants.DEMO_SESSION_PLAN[: constants.DEMO_MAX_SESSIONS]
    ]


def build_demo(database_path: Path, size: DemoSize, first_day: date, seed: int | None = None) -> Database:
    """Create a fresh demo database with a meet, sessions and signed-in officials.

    Every session gets exactly the stroke & turn judges and trainees asked for (a
    random selection of one shared crew), plus the corner officials when ticked. One
    judge in the first session is left "card not checked" for the admin.

    Args:
        database_path: Demo SQLite file (deleted and recreated).
        size: Sessions and how many sign in to each.
        first_day: Date of the first session.
        seed: Random seed (None for a different demo each time).

    Returns:
        The demo database, ready to use.
    """
    for suffix in ("", *_SQLITE_SIDE_FILE_SUFFIXES):
        Path(str(database_path) + suffix).unlink(missing_ok=True)
    database = Database(database_path)
    database.initialize()
    generator = random.Random(seed)
    meet_id = database.create_meet(constants.DEMO_MEET_NAME, first_day.isoformat())
    session_ids = []
    for day_offset, session_type, start_time in constants.DEMO_SESSION_PLAN[: len(size.sessions)]:
        session_date = first_day + timedelta(days=day_offset)
        start_minutes = int(start_time[:2]) * constants.MINUTES_PER_HOUR + int(start_time[3:])
        meeting_minutes = start_minutes - constants.OFFICIALS_MEETING_MINUTES_BEFORE_START
        meeting = f"{meeting_minutes // constants.MINUTES_PER_HOUR:02d}:{meeting_minutes % constants.MINUTES_PER_HOUR:02d}"
        session_ids.append(database.add_session(
            session_name(session_date, session_type), session_date.isoformat(), start_time, session_type, meeting,
            constants.DEFAULT_SESSION_MINUTES,
        ))

    # The crew: enough judges and trainees for the busiest session, plus the corner officials.
    judge_pool = max(session.judges for session in size.sessions)
    trainee_pool = max(session.trainees for session in size.sessions)
    corner_roles = list(constants.DEMO_SPECIAL_ROLES) if size.corner_officials else []
    names = iter(fake_names(len(corner_roles) + judge_pool + trainee_pool, generator))
    lsc = generator.choice(constants.DEMO_LSC_CODES)

    def add_official(trainee: bool, head_official: bool) -> int:
        """Store one made-up official; returns their ID."""
        if generator.random() < constants.DEMO_UNKNOWN_YEARS_SHARE:
            years = None
        else:
            years = 0 if trainee else demo_years(generator, head_official)
        official_id = database.save_official(None, next(names), years, None, None, first_day)
        _set_club(database, official_id, lsc, generator.choice(constants.DEMO_CLUB_CODES), meet_id)
        return official_id

    role_of = {add_official(False, True): role for role in corner_roles}
    judges = [add_official(False, False) for _ in range(judge_pool)]
    trainees = [add_official(True, False) for _ in range(trainee_pool)]

    # Who works which session: the corner officials every session; each session a random
    # selection of the crew, exactly as many as asked for.
    attending: dict[int, list[int]] = {official_id: list(session_ids) for official_id in role_of}
    for session_id, session in zip(session_ids, size.sessions):
        for official_id in generator.sample(judges, session.judges) + generator.sample(trainees, session.trainees):
            attending.setdefault(official_id, []).append(session_id)

    needs_admin_left = constants.DEMO_NEEDS_ADMIN_COUNT
    first_session = session_ids[0]
    trainee_ids = set(trainees)
    for official_id, sessions in attending.items():
        validations = {session_id: Validation(True, constants.VALIDATION_CAMERA, []) for session_id in sessions}
        if needs_admin_left > 0 and official_id not in role_of and official_id not in trainee_ids and first_session in sessions:
            validations[first_session] = not_checked_validation()
            needs_admin_left -= 1
        role = role_of.get(official_id, constants.TEAM_POOL_ROLE)
        database.sign_in(official_id, sorted(sessions), [role], official_id in trainee_ids, validations)
    database.set_text_setting(constants.SETTING_DEMO_SIZE, json.dumps(size.to_payload()))
    return database


def stored_demo_size(database: Database) -> DemoSize:
    """The size the demo was last built with, for "Reset demo" (the default if unknown)."""
    stored = database.get_text_setting(constants.SETTING_DEMO_SIZE)
    if stored:
        try:
            return DemoSize.from_payload(json.loads(stored))
        except (ValueError, json.JSONDecodeError):
            pass
    return default_demo_size()


def _set_club(database: Database, official_id: int, lsc: str, club: str, meet_id: int) -> None:
    """Give a demo official an LSC and club (as a card read would)."""
    with database._connect() as connection:  # noqa: SLF001 (demo helper, same package)
        connection.execute(
            "UPDATE officials SET lsc = ?, club = ?, card_meet_id = ? WHERE id = ?", (lsc, club, meet_id, official_id)
        )
