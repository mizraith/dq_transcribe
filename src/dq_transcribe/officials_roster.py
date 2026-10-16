"""Read an officials roster file from the Officials Sign-In app.

The format (``officials-roster``, version 1) is owned by the officials_signin app
and written up in ``ai_docs/officials_roster_format.md``. dq_transcribe uses only
each official's name and role (to suggest names on DQs and fill in the official's
role); everything else in the file is ignored here. Member IDs in particular are
personal data: they are never stored or logged by this app.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from dq_transcribe import constants

ROSTER_FORMAT = "officials-roster"
SUPPORTED_VERSION = 1


class RosterError(Exception):
    """The file is not an officials roster this app can read (message shown to the admin)."""


@dataclass
class ImportedRoster:
    """What was read from a roster file."""

    officials: list[dict[str, Any]] = field(default_factory=list)  # [{"name", "role", "trainee"}]
    session: str = ""  # "Friday PM, 2026-10-16"
    meet_name: str = ""
    warnings: list[str] = field(default_factory=list)


def read_roster(raw: bytes) -> ImportedRoster:
    """Read a roster file's officials (name and role only).

    Args:
        raw: The file's bytes (JSON).

    Returns:
        The officials (one entry per name and role), the session, and warnings for
        anything skipped.

    Raises:
        RosterError: If the file is not an officials roster.
    """
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RosterError("This is not an officials roster file (not JSON).") from error
    if not isinstance(payload, dict) or payload.get("format") != ROSTER_FORMAT:
        raise RosterError("This is not an officials roster file from the Officials Sign-In app.")
    roster = ImportedRoster()
    version = payload.get("version")
    if not isinstance(version, int) or version > SUPPORTED_VERSION:
        roster.warnings.append(f"Roster format version {version} is newer than this app knows ({SUPPORTED_VERSION}); read what it could.")
    session = payload.get("session") or {}
    meet = payload.get("meet") or {}
    if isinstance(session, dict):
        roster.session = ", ".join(str(part) for part in (session.get("name"), session.get("date")) if part)
    if isinstance(meet, dict):
        roster.meet_name = str(meet.get("name") or "")
    seen: set[tuple[str, str]] = set()
    for entry in payload.get("officials") or []:
        if not isinstance(entry, dict):
            continue
        name = " ".join(str(entry.get("name") or "").split())[: constants.MAX_MEET_NAME_CHARS]
        role = entry.get("role")
        if not name:
            continue
        if role not in constants.MEET_ROSTER_ROLES:
            roster.warnings.append(f"Skipped {name}: unknown role {role!r}.")
            continue
        if (name, role) in seen:
            continue
        seen.add((name, role))
        roster.officials.append({"name": name, "role": role, "trainee": bool(entry.get("trainee"))})
    if len(roster.officials) > constants.MAX_MEET_OFFICIALS:
        roster.warnings.append(f"Only the first {constants.MAX_MEET_OFFICIALS} officials were read.")
        roster.officials = roster.officials[: constants.MAX_MEET_OFFICIALS]
    return roster
