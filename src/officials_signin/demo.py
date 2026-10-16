"""Demo meet: a separate database filled with made-up officials.

Lets anyone try the whole workflow (the sign-in list and admin exceptions, Teams,
printouts, the roster) without touching the real meet. The demo lives in its own
SQLite file (``constants.DEMO_DATABASE_PATH``) and is rebuilt from scratch every
time a demo is started.

Names are invented from short first/last-name lists; clubs use made-up codes
(``DMOA``...) so nothing looks like a real person or club.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

from officials_signin import constants
from officials_signin.database import Database, Validation, not_checked_validation

_SQLITE_SIDE_FILE_SUFFIXES = ("-wal", "-shm")
_SIZE_SETTINGS = (
    constants.SETTING_DEMO_JUDGES,
    constants.SETTING_DEMO_TRAINEES,
    constants.SETTING_DEMO_SESSIONS,
    constants.SETTING_DEMO_HEAD_OFFICIALS,
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


def assign_roles(judge_count: int, trainee_count: int, head_officials: bool) -> list[tuple[str, bool]]:
    """Roles for a demo crew.

    Args:
        judge_count: Certified stroke & turn judges (these make the teams).
        trainee_count: Stroke & turn trainees (shadow a mentor).
        head_officials: Also add a meet referee, deck referee, starter, chief judge and admin official.

    Returns:
        ``(role, trainee)`` per official, in order.
    """
    roles = [(role, False) for role in constants.DEMO_SPECIAL_ROLES] if head_officials else []
    roles += [(constants.TEAM_POOL_ROLE, False)] * judge_count
    roles += [(constants.TEAM_POOL_ROLE, True)] * trainee_count
    return roles


def session_name(session_date: date, session_type: str) -> str:
    """``Friday PM``, ``Saturday Prelims`` (same style as Meet setup's suggestion)."""
    return f"{session_date.strftime('%A')} {session_type}"


def build_demo(
    database_path: Path,
    judge_count: int,
    trainee_count: int,
    session_count: int,
    head_officials: bool,
    first_day: date,
    seed: int | None = None,
) -> Database:
    """Create a fresh demo database with a meet, sessions and signed-in officials.

    Args:
        database_path: Demo SQLite file (deleted and recreated).
        judge_count: Certified stroke & turn judges.
        trainee_count: Stroke & turn trainees.
        session_count: Sessions (1 to ``constants.DEMO_MAX_SESSIONS``).
        head_officials: Add referees, starter, chief judge and admin official.
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
    for day_offset, session_type, start_time in constants.DEMO_SESSION_PLAN[:session_count]:
        session_date = first_day + timedelta(days=day_offset)
        start_minutes = int(start_time[:2]) * constants.MINUTES_PER_HOUR + int(start_time[3:])
        meeting_minutes = start_minutes - constants.OFFICIALS_MEETING_MINUTES_BEFORE_START
        meeting = f"{meeting_minutes // constants.MINUTES_PER_HOUR:02d}:{meeting_minutes % constants.MINUTES_PER_HOUR:02d}"
        session_ids.append(database.add_session(
            session_name(session_date, session_type), session_date.isoformat(), start_time, session_type, meeting,
            constants.DEFAULT_SESSION_MINUTES,
        ))
    lsc = generator.choice(constants.DEMO_LSC_CODES)
    needs_admin_left = constants.DEMO_NEEDS_ADMIN_COUNT
    roles = assign_roles(judge_count, trainee_count, head_officials)
    for name, (role, trainee) in zip(fake_names(len(roles), generator), roles):
        years = None if generator.random() < constants.DEMO_UNKNOWN_YEARS_SHARE else (
            0 if trainee else generator.randint(1, constants.DEMO_MAX_YEARS_CERTIFIED)
        )
        official_id = database.save_official(None, name, years, None, None, first_day)
        _set_club(database, official_id, lsc, generator.choice(constants.DEMO_CLUB_CODES), meet_id)
        # Everyone works the first session (so its count matches what was asked for);
        # later sessions are each skipped now and then.
        attending = session_ids[:1] + [
            session_id for session_id in session_ids[1:] if generator.random() < constants.DEMO_ATTENDANCE_SHARE
        ]
        validations = {}
        for session_id in attending:
            if needs_admin_left > 0 and role == constants.TEAM_POOL_ROLE and not trainee:
                validations[session_id] = not_checked_validation()
            else:
                validations[session_id] = Validation(True, constants.VALIDATION_CAMERA, [])
        if any(not validation.validated for validation in validations.values()):
            needs_admin_left -= 1
        database.sign_in(official_id, attending, [role], trainee, validations)
    for key, value in zip(_SIZE_SETTINGS, (judge_count, trainee_count, session_count, int(head_officials))):
        database.set_setting(key, value)
    return database


def stored_demo_size(database: Database) -> tuple[int, int, int, bool]:
    """The size the demo was last built with, for "Reset demo" (the defaults if unknown).

    Returns:
        ``(judge_count, trainee_count, session_count, head_officials)``.
    """
    defaults = (
        constants.DEMO_DEFAULT_JUDGES, constants.DEMO_DEFAULT_TRAINEES, constants.DEMO_DEFAULT_SESSIONS, 1,
    )
    judges, trainees, sessions, head = (
        default if (value := database.get_setting(key)) is None else value
        for key, default in zip(_SIZE_SETTINGS, defaults)
    )
    return judges, trainees, sessions, bool(head)


def _set_club(database: Database, official_id: int, lsc: str, club: str, meet_id: int) -> None:
    """Give a demo official an LSC and club (as a card read would)."""
    with database._connect() as connection:  # noqa: SLF001 (demo helper, same package)
        connection.execute(
            "UPDATE officials SET lsc = ?, club = ?, card_meet_id = ? WHERE id = ?", (lsc, club, meet_id, official_id)
        )
