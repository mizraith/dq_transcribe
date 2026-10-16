"""Build the officials roster file that dq_transcribe imports.

The format is the contract between the two apps; it is documented in
``ai_docs/officials_roster_format.md``. An official working two roles appears
twice, once per role.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from officials_signin import constants

_NON_FILENAME_CHARACTERS = re.compile(r"[^a-z0-9]+")


def build_roster(source: dict[str, Any], generated_at: datetime | None = None) -> dict[str, Any]:
    """Turn a session's sign-ins into the roster file.

    Args:
        source: Output of ``Database.roster_source``.
        generated_at: Time stamp for the file (defaults to now, local time with offset).

    Returns:
        The roster, ready for ``json.dumps``.
    """
    moment = generated_at or datetime.now().astimezone()
    meet = source[constants.KEY_MEET]
    session = source[constants.ROSTER_KEY_SESSION]
    officials = []
    names = {signin[constants.KEY_ID]: signin[constants.KEY_NAME] for signin in source[constants.KEY_SIGNINS]}
    for signin in sorted(source[constants.KEY_SIGNINS], key=lambda item: item[constants.KEY_NAME].lower()):
        for role in signin[constants.KEY_ROLES]:
            officials.append(
                {
                    constants.KEY_NAME: signin[constants.KEY_NAME],
                    constants.KEY_ROLE: role,
                    constants.KEY_CLUB: signin[constants.KEY_CLUB],
                    constants.KEY_ZONE: signin[constants.KEY_ZONE],
                    constants.KEY_YEARS_CERTIFIED: signin[constants.KEY_YEARS_CERTIFIED],
                    constants.KEY_TRAINEE: signin[constants.KEY_TRAINEE],
                    constants.KEY_VALIDATED: signin[constants.KEY_VALIDATED],
                    constants.KEY_VALIDATION_METHOD: signin[constants.KEY_VALIDATION_METHOD],
                    constants.KEY_TEAM: signin[constants.KEY_TEAM],
                    constants.KEY_MEMBER_ID: signin.get(constants.KEY_MEMBER_ID),
                    # Optional keys added within version 1 (team builder).
                    constants.KEY_TEAM_LEAD: bool(signin.get(constants.KEY_TEAM_LEAD)),
                    constants.KEY_ASSIGNMENT: signin.get(constants.KEY_ASSIGNMENT),
                    constants.KEY_MENTOR: names.get(signin.get(constants.KEY_MENTOR_SIGNIN_ID)),
                }
            )
    return {
        constants.ROSTER_KEY_FORMAT: constants.ROSTER_FORMAT_NAME,
        constants.ROSTER_KEY_VERSION: constants.ROSTER_FORMAT_VERSION,
        constants.ROSTER_KEY_GENERATED_AT: moment.isoformat(timespec="seconds"),
        constants.ROSTER_KEY_MEET: {
            constants.KEY_NAME: meet[constants.KEY_NAME],
            constants.KEY_START_DATE: meet[constants.KEY_START_DATE],
        },
        constants.ROSTER_KEY_SESSION: {
            constants.KEY_NAME: session[constants.KEY_NAME],
            constants.KEY_DATE: session[constants.KEY_DATE],
            constants.KEY_START_TIME: session[constants.KEY_START_TIME],
            # Optional keys added within version 1 (readers ignore keys they do not know).
            constants.ROSTER_KEY_SESSION_TYPE: session.get(constants.KEY_SESSION_TYPE),
            constants.KEY_OFFICIALS_MEETING_TIME: session.get(constants.KEY_OFFICIALS_MEETING_TIME),
        },
        constants.ROSTER_KEY_OFFICIALS: officials,
    }


def roster_download_filename(roster: dict[str, Any]) -> str:
    """File name for a downloaded roster, for example ``officials_roster_2026-10-16_friday-pm.json``."""
    session_name = roster[constants.ROSTER_KEY_SESSION][constants.KEY_NAME]
    slug = _NON_FILENAME_CHARACTERS.sub("-", session_name.lower()).strip("-") or "session"
    return constants.ROSTER_DOWNLOAD_FILENAME_FORMAT.format(
        start_date=roster[constants.ROSTER_KEY_SESSION][constants.KEY_DATE], session_slug=slug
    )
