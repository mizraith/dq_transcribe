"""Save a meet as a zip file: a record to keep after the meet (or before deleting it).

The zip holds everything about a meet in files that open without the app:

- ``README.txt``: what is inside.
- ``meet_summary.html``: every session's officials (the printable meet summary).
- ``sessions/NN_<session>_officials.html``: one page per session (the session summary).
- ``sessions/NN_<session>_teams.html``: the team page, for sessions with teams.
- ``signins.csv``: one row per official per session, for a spreadsheet.
- ``coaches.csv``: the coaches of every session (club, head coach, check).
- ``rosters/NN_<session>.json``: the roster file dq_transcribe reads, per session.
- ``meet.json``: the meet and its sessions' settings (lanes, teams, rotation...).

**Member IDs are left out of every file** (the roster files carry ``null``), so the
zip can be kept or shared without personal data beyond names and clubs.
"""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from datetime import datetime
from typing import Any

from officials_signin import constants
from officials_signin.coaches import ensure_tables, list_coach_signins
from officials_signin.database import Database
from officials_signin.reports import check_text, render_meet_summary, render_session_summary, render_team_display
from officials_signin.roster import build_roster
from officials_signin.teams import build_team_view

_NON_FILENAME_CHARACTERS = re.compile(r"[^a-z0-9]+")
_FILENAME_TIME_FORMAT = "%Y-%m-%d_%H%M"
_README = """{meet_name} (starts {start_date})
Saved by Officials Sign-In on {saved_at}.

meet_summary.html      Every session's officials (open in a browser, print if needed).
sessions/              Each session's officials page, and its team page when teams were built.
signins.csv            One row per official per session (opens in a spreadsheet).
coaches.csv            The coaches of every session (club, head coach).
rosters/               The roster files dq_transcribe reads, one per session.
meet.json              The meet and its sessions' settings.

Member IDs are not included in any of these files.
"""
_CSV_COLUMNS = (
    "Session", "Date", "Name", "Roles", "Trainee", "Team", "Job", "Team Lead", "Mentor",
    "Club", "LSC", "Zone", "Years certified", "Checked",
)


def slug(text: str) -> str:
    """``Friday PM`` -> ``friday-pm`` (for file names)."""
    return _NON_FILENAME_CHARACTERS.sub("-", text.lower()).strip("-") or "meet"


def zip_filename(meet: dict[str, Any], saved_at: datetime) -> str:
    """For example ``fall-classic_2026-10-16_officials_saved_2026-10-18_2105.zip``."""
    return constants.MEET_ZIP_FILENAME_FORMAT.format(
        meet_slug=slug(meet[constants.KEY_NAME]),
        start_date=meet[constants.KEY_START_DATE],
        saved=saved_at.strftime(_FILENAME_TIME_FORMAT),
    )


def _csv_rows(session: dict[str, Any], signins: list[dict[str, Any]]) -> list[list[Any]]:
    """The CSV rows for one session, sorted by name (no member IDs)."""
    names_by_id = {signin[constants.KEY_ID]: signin[constants.KEY_NAME] for signin in signins}
    rows = []
    for signin in sorted(signins, key=lambda item: item[constants.KEY_NAME].lower()):
        rows.append([
            session[constants.KEY_NAME],
            session[constants.KEY_DATE],
            signin[constants.KEY_NAME],
            ", ".join(signin[constants.KEY_ROLES]),
            "yes" if signin[constants.KEY_TRAINEE] else "",
            signin[constants.KEY_TEAM] or "",
            signin[constants.KEY_ASSIGNMENT] or "",
            "yes" if signin[constants.KEY_TEAM_LEAD] else "",
            names_by_id.get(signin[constants.KEY_MENTOR_SIGNIN_ID]) or "",
            signin[constants.KEY_CLUB] or "",
            signin[constants.KEY_LSC] or "",
            signin[constants.KEY_ZONE] or "",
            "" if signin[constants.KEY_YEARS_CERTIFIED] is None else signin[constants.KEY_YEARS_CERTIFIED],
            check_text(signin),
        ])
    return rows


def _coaches_csv(database: Database, sessions: list[dict[str, Any]]) -> str:
    """The coaches of every session (club, name, head coach, check), for a spreadsheet."""
    ensure_tables(database)
    text = io.StringIO()
    writer = csv.writer(text)
    writer.writerow(("Session", "Date", "Club", "LSC", "Name", "Head coach", "Checked"))
    for session in sessions:
        coaches = list_coach_signins(database, session[constants.KEY_ID])
        for coach in sorted(coaches, key=lambda item: ((item[constants.KEY_CLUB] or "~"), item[constants.KEY_NAME].lower())):
            writer.writerow((
                session[constants.KEY_NAME], session[constants.KEY_DATE], coach[constants.KEY_CLUB] or "",
                coach[constants.KEY_LSC] or "", coach[constants.KEY_NAME],
                "yes" if coach[constants.KEY_HEAD_COACH] else "", check_text(coach),
            ))
    return text.getvalue()


def build_meet_zip(database: Database, meet_id: int, saved_at: datetime | None = None) -> tuple[str, bytes]:
    """Build the zip for one meet.

    Args:
        database: The database holding the meet (real or demo).
        meet_id: The meet.
        saved_at: Time stamp for the file name and pages (defaults to now).

    Returns:
        ``(file name, zip bytes)``.

    Raises:
        LookupError: When there is no such meet.
    """
    meet = database.get_meet(meet_id)
    if meet is None:
        raise LookupError("No such meet")
    moment = saved_at or datetime.now().astimezone()
    sessions = database.list_sessions(meet_id)
    pairs = [(session, database.list_signins(session[constants.KEY_ID])) for session in sessions]
    buffer = io.BytesIO()
    folder = slug(meet[constants.KEY_NAME])
    csv_text = io.StringIO()
    writer = csv.writer(csv_text)
    writer.writerow(_CSV_COLUMNS)
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{folder}/README.txt", _README.format(
            meet_name=meet[constants.KEY_NAME], start_date=meet[constants.KEY_START_DATE],
            saved_at=moment.strftime("%Y-%m-%d %H:%M"),
        ))
        archive.writestr(f"{folder}/meet_summary.html", render_meet_summary(meet, pairs, standalone=True))
        for number, (session, signins) in enumerate(pairs, start=1):
            stem = f"{number:02d}_{slug(session[constants.KEY_NAME])}"
            archive.writestr(
                f"{folder}/sessions/{stem}_officials.html", render_session_summary(meet, session, signins, standalone=True)
            )
            if session.get(constants.KEY_TEAMS_BUILT_AT):
                view = build_team_view(signins, session)
                archive.writestr(
                    f"{folder}/sessions/{stem}_teams.html",
                    render_team_display(meet, session, view, len(signins), standalone=True),
                )
            source = database.roster_source(session[constants.KEY_ID])
            for signin in source[constants.KEY_SIGNINS]:
                signin[constants.KEY_MEMBER_ID] = None  # never in a saved file
            archive.writestr(
                f"{folder}/rosters/{stem}.json", json.dumps(build_roster(source, moment), indent=1, ensure_ascii=False)
            )
            writer.writerows(_csv_rows(session, signins))
        archive.writestr(f"{folder}/signins.csv", csv_text.getvalue())
        archive.writestr(f"{folder}/coaches.csv", _coaches_csv(database, sessions))
        archive.writestr(f"{folder}/meet.json", json.dumps({
            constants.KEY_MEET: meet,
            constants.KEY_SESSIONS: sessions,
            constants.KEY_SAVED_AT: moment.isoformat(timespec="seconds"),
        }, indent=1, ensure_ascii=False, default=str))
    return zip_filename(meet, moment), buffer.getvalue()

