"""Timestamps and call/response grouping for dq_transcribe.

Clips carry the wall-clock time they were captured. Clips that follow each
other closely (a call and its response) are grouped together. Grouping is
computed when needed rather than stored, so the gap setting can be changed at
any time without reprocessing audio.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from dq_transcribe import constants


def parse_timestamp(value: str) -> datetime:
    """Parse an ISO 8601 timestamp, treating a trailing ``Z`` as UTC.

    Args:
        value: Timestamp text, for example ``"2026-10-10T19:43:05.123Z"``.

    Returns:
        A timezone-aware datetime (naive input is assumed to be UTC).

    Raises:
        ValueError: If the text is not a valid timestamp.
    """
    if value.endswith(constants.TIMESTAMP_UTC_SUFFIX):
        value = value[: -len(constants.TIMESTAMP_UTC_SUFFIX)] + constants.TIMESTAMP_UTC_OFFSET
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def normalize_timestamp(value: str) -> str | None:
    """Validate a timestamp and rewrite it as UTC with millisecond precision.

    Args:
        value: Timestamp text from a client.

    Returns:
        The normalized text, or None if the value is not a valid timestamp.
    """
    try:
        return parse_timestamp(value).astimezone(timezone.utc).isoformat(timespec="milliseconds")
    except (ValueError, OverflowError):
        return None


def clip_start(clip: dict[str, Any]) -> datetime:
    """When a clip's audio began (falls back to its upload time)."""
    return parse_timestamp(clip["started_at"] or clip["created_at"])


def clip_end(clip: dict[str, Any]) -> datetime:
    """When a clip's audio ended (falls back to its start plus its duration, then upload time)."""
    if clip["ended_at"]:
        return parse_timestamp(clip["ended_at"])
    if clip["started_at"] and clip.get("duration_seconds"):
        return parse_timestamp(clip["started_at"]) + timedelta(seconds=clip["duration_seconds"])
    return parse_timestamp(clip["created_at"])


def assign_conversation_groups(
    clips: list[dict[str, Any]],
    gap_seconds: float = constants.CONVERSATION_GAP_SECONDS,
) -> None:
    """Add a ``group_id`` to every clip, grouping clips that follow each other closely.

    A new group starts when the silence between the end of one clip and the
    start of the next is at least ``gap_seconds``. The ``group_id`` is the id of
    the first clip in the group.

    Args:
        clips: Clip dictionaries in any order; each needs ``id``, ``created_at``,
            ``started_at``, ``ended_at`` and ``duration_seconds``. Modified in place.
        gap_seconds: Shortest gap that starts a new group.
    """
    previous_end: datetime | None = None
    group_id: int | None = None
    for clip in sorted(clips, key=lambda item: (clip_start(item), item["id"])):
        start = clip_start(clip)
        starts_new_group = (
            previous_end is None or (start - previous_end).total_seconds() >= gap_seconds
        )
        if starts_new_group:
            group_id = clip["id"]
        clip["group_id"] = group_id
        end = clip_end(clip)
        previous_end = end if previous_end is None else max(previous_end, end)
