"""Automatic DQs: turn detected radio calls into DQs without a tap.

The owner's rule for the first real meet (2026-10-16): the app does as much as
it can on its own and the admin is the gatekeeper at the **notify** step. So a
background thread watches the active meet's transcripts and, for each detected
call (``DqStore.candidates``):

* **creates the DQ** with what was heard: event, heat, lane, infractions and their
  slip codes, phases and the audio evidence. It starts as Accepted when the
  referee's acknowledgment was heard, otherwise as Called. The swimmer and club
  are filled from the meet file (``DqStore.create_dq`` does that), and the
  referee and chief judge from the roster when the meet has exactly one of each;
* **adds later calls on the same swimmer** (same event, heat and lane) to that
  DQ instead of making another: calls come in pieces many seconds apart (IM,
  longer races) and are sometimes repeated (``DqStore.add_call``);
* **marks it Accepted later** if the acknowledgment arrives in a later clip, as
  long as nobody has changed the DQ's state by hand.

What it leaves alone, for a person:

* calls with no lane, or "not understood" (they stay in the transcript as
  detected calls, with their "+ DQ" button);
* calls whose clips are still being transcribed: it waits for the slower,
  more accurate refine pass, but at most ``constants.AUTO_DQ_MAX_REFINE_WAIT_SECONDS``
  (the refine pass only runs in the gaps between calls);
* anything already a DQ, dismissed, or moved to the trash (a trashed auto DQ is
  never made again).

Turned on and off in Meet setup (an app setting, on by default). Work only
happens when the meet's clips, transcripts or DQs changed since the last look.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from dq_transcribe import constants
from dq_transcribe.call_parser import FLAG_NOT_UNDERSTOOD
from dq_transcribe.database import Database
from dq_transcribe.dq_store import DqError, DqStore

LOGGER = logging.getLogger(__name__)
AUTO_BY_NAME = "Auto"  # who the history says made the change
CREATED_NOTE = "created automatically from a detected call"
ACCEPTED_NOTE = "acknowledgment heard on the radio"
# Clip refine states after which the text will not change any more.
_FINAL_REFINE_STATES = {
    None, constants.CLIP_STATUS_DONE, constants.CLIP_STATUS_FAILED, constants.REFINE_STATUS_SKIPPED,
}


def candidate_payload(candidate: dict[str, Any], roster_fill: dict[str, str]) -> dict[str, Any]:
    """The DQ to create from a detected call (as the "+ DQ" button would, plus roster guesses).

    Args:
        candidate: A detected call from ``DqStore.candidates``.
        roster_fill: Field -> name for roster roles the meet has exactly one of.
    """
    payload: dict[str, Any] = {
        "event": candidate.get("event"),
        "heat": candidate.get("heat"),
        "lane": candidate.get("lane"),
        "accepted": bool(candidate.get("accepted")),
        constants.REQUEST_KEY_INFRACTIONS: [
            {
                "description": description,
                "code": _list_item(candidate.get("codes"), index),
                "code_options": _code_options(candidate, index),
                "phases": candidate.get("phases") or [],
            }
            for index, description in enumerate(candidate.get("infractions") or [])
        ],
        constants.REQUEST_KEY_EVIDENCE: candidate.get("evidence") or [],
        constants.REQUEST_KEY_CANDIDATE_KEY: candidate["key"],
    }
    payload.update(roster_fill)
    return payload


def _list_item(values: list[Any] | None, index: int) -> Any:
    """``values[index]``, or None when the list is missing or too short."""
    return values[index] if values and index < len(values) else None


def _code_options(candidate: dict[str, Any], index: int) -> list[str]:
    """The slip codes that fit infraction ``index`` (or the whole call's suggestions)."""
    options = candidate.get("code_options") or []
    if index < len(options) and options[index]:
        return list(options[index])
    return list(candidate.get("suggested_codes") or [])


def roster_guesses(officials: list[dict[str, str]]) -> dict[str, str]:
    """DQ fields that can be filled from the roster: the role's only official.

    The referee is the Deck Referee (or the Meet Referee if there is no Deck
    Referee); the chief judge is the Chief Judge. Nothing is guessed when the
    roster has two or more people in that role.
    """
    by_role: dict[str, list[str]] = {}
    for official in officials:
        by_role.setdefault(official["role"], []).append(official["name"])
    guesses: dict[str, str] = {}
    for field_name, roles in constants.AUTO_DQ_ROSTER_FIELDS.items():
        for role in roles:
            names = by_role.get(role, [])
            if len(names) == 1:
                guesses[field_name] = names[0]
                break
            if names:
                break  # several people in this role: leave it for the admin
    return guesses


class AutoDqCreator:
    """Background thread that makes DQs from detected calls (see the module docstring).

    Attributes:
        database: App storage.
        dq_store: DQ storage (also finds the detected calls).
    """

    def __init__(self, database: Database, dq_store: DqStore, poll_seconds: float = constants.AUTO_DQ_POLL_SECONDS) -> None:
        """Prepare; nothing runs until ``start``."""
        self.database = database
        self.dq_store = dq_store
        self._poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_signature: tuple[Any, ...] | None = None

    @property
    def enabled(self) -> bool:
        """True unless the admin turned automatic DQs off in Meet setup."""
        return self.database.get_setting(constants.SETTING_AUTO_CREATE_DQS, constants.SETTING_TRUE) == constants.SETTING_TRUE

    def set_enabled(self, enabled: bool) -> None:
        """Turn automatic DQs on or off (remembered across restarts)."""
        self.database.set_setting(constants.SETTING_AUTO_CREATE_DQS, constants.SETTING_TRUE if enabled else constants.SETTING_FALSE)
        self._last_signature = None  # look again at once when turned back on

    def start(self) -> None:
        """Start the background thread."""
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="auto-dq", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the background thread."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        """Look for new calls every few seconds until stopped (never dies on an error)."""
        while not self._stop.wait(self._poll_seconds):
            try:
                self.run_once()
            except Exception:  # noqa: BLE001 (log and keep going: the meet goes on)
                LOGGER.exception("Automatic DQs: unexpected error")

    def run_once(self, now: datetime | None = None) -> dict[str, list[int]]:
        """Make DQs from the active meet's new calls, and accept those whose acknowledgment came later.

        Returns:
            ``{"created": [dq ids], "added_to": [dq ids a later call was added to], "accepted": [dq ids]}``.
        """
        result: dict[str, list[int]] = {"created": [], "added_to": [], "accepted": []}
        meet_id = self.database.get_active_meet_id()
        if meet_id is None or not self.enabled:
            return result
        signature = self._signature(meet_id)
        if signature == self._last_signature:
            return result
        now = now or datetime.now(timezone.utc)
        clips = {clip["id"]: clip for clip in self.database.list_clips(meet_id=meet_id)}
        meet = self.database.get_meet(meet_id) or {}
        roster_fill = roster_guesses(self._officials(meet_id))
        waiting = False
        for candidate in self.dq_store.candidates(meet_id, include_used=True):
            clip_ids = {item["clip_id"] for item in candidate.get("evidence") or []}
            if not all(self._clip_is_final(clips.get(clip_id), now) for clip_id in clip_ids):
                waiting = True  # look again on the next pass even if nothing else changes
                continue
            if candidate.get("used"):
                dq_id = self._accept_if_heard_later(candidate)
                if dq_id is not None:
                    result["accepted"].append(dq_id)
                continue
            if not candidate.get("lane") or FLAG_NOT_UNDERSTOOD in (candidate.get("flags") or []):
                continue  # not enough to go on: a person makes this one from the transcript
            try:
                dq_id, added = self.dq_store.add_call(candidate_payload(candidate, roster_fill), meet_id, note=CREATED_NOTE)
            except DqError as error:
                LOGGER.info("Automatic DQs: skipped call %s (%s)", candidate["key"], error)
                continue
            result["added_to" if added else "created"].append(dq_id)
        if any(result.values()):
            LOGGER.info("Automatic DQs in %s: %s", meet.get("name"), result)
        # Our own changes alter the signature: take it after them, so the next pass skips.
        self._last_signature = None if waiting else self._signature(meet_id)
        return result

    # --- Helpers ---------------------------------------------------------------------

    def _signature(self, meet_id: int) -> tuple[Any, ...]:
        """A cheap summary of the meet's clips, transcripts, DQs and roster: unchanged means nothing to do."""
        with self.database.connection() as connection:
            clips = connection.execute(
                "SELECT COUNT(*), MAX(id), GROUP_CONCAT(id || ':' || status || ':' || COALESCE(refine_status, '')) "
                "FROM clips WHERE meet_id = ?",
                (meet_id,),
            ).fetchone()
            edits = connection.execute(
                "SELECT MAX(u.edited_at) FROM utterances u JOIN clips c ON c.id = u.clip_id WHERE c.meet_id = ?", (meet_id,)
            ).fetchone()
            dqs = connection.execute("SELECT COUNT(*), MAX(updated_at) FROM dqs WHERE meet_id = ?", (meet_id,)).fetchone()
            dismissed = connection.execute("SELECT COUNT(*) FROM candidate_dismissals").fetchone()
        return (meet_id, tuple(clips), tuple(edits), tuple(dqs), tuple(dismissed), tuple(sorted(self._roster_tuple(meet_id))))

    def _officials(self, meet_id: int) -> list[dict[str, str]]:
        """The meet's roster ({name, role})."""
        meet = next((item for item in self.database.list_meets() if item["id"] == meet_id), None)
        return list(meet.get("officials") or []) if meet else []

    def _roster_tuple(self, meet_id: int) -> list[tuple[str, str]]:
        """The roster as sortable pairs (for the signature)."""
        return [(official["role"], official["name"]) for official in self._officials(meet_id)]

    @staticmethod
    def _clip_is_final(clip: dict[str, Any] | None, now: datetime) -> bool:
        """True once a clip's text will not change (refined, or waited long enough)."""
        if clip is None or clip["status"] != constants.CLIP_STATUS_DONE:
            return False
        if clip.get("refine_status") in _FINAL_REFINE_STATES:
            return True
        try:
            created = datetime.fromisoformat(clip["created_at"])
        except (TypeError, ValueError):
            return True
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return now - created >= timedelta(seconds=constants.AUTO_DQ_MAX_REFINE_WAIT_SECONDS)

    def _accept_if_heard_later(self, candidate: dict[str, Any]) -> int | None:
        """Accept an automatic DQ still Called once its acknowledgment is heard (never one a person changed)."""
        if not candidate.get("accepted"):
            return None
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT id, state, source FROM dqs WHERE id = ? AND trashed_at IS NULL", (self.dq_store.dq_for_call(candidate["key"]),)
            ).fetchone()
            if row is None or row["state"] != constants.DQ_STATE_CALLED or row["source"] != constants.DQ_SOURCE_AUTO:
                return None
            changed_by_hand = connection.execute(
                "SELECT COUNT(*) FROM dq_history WHERE dq_id = ? AND from_state IS NOT NULL", (row["id"],)
            ).fetchone()[0]
        if changed_by_hand:
            return None
        if self.dq_store.change_state(row["id"], constants.DQ_STATE_ACCEPTED, AUTO_BY_NAME, ACCEPTED_NOTE):
            return int(row["id"])
        return None
