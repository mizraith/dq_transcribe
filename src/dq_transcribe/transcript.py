"""Plain-text transcript output for dq_transcribe.

Each turn (one radio transmission) is written on its own line with a time
stamp. A blank line separates call/response groups.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from dq_transcribe import constants
from dq_transcribe.grouping import assign_conversation_groups, clip_start


def format_transcript_text(clips: list[dict[str, Any]]) -> str:
    """Build a readable transcript from clips.

    Args:
        clips: Clip dictionaries from ``Database.list_clips``, each with
            ``utterances``. Grouping is (re)computed here.

    Returns:
        One ``[HH:MM:SS] text`` line per turn in chronological order, in the
        device's local time, with a blank line between call/response groups.
        Clips without utterances are skipped.
    """
    assign_conversation_groups(clips)
    lines: list[str] = []
    previous_group_id: int | None = None
    for clip in sorted(clips, key=lambda item: (clip_start(item), item["id"])):
        if not clip["utterances"]:
            continue
        if previous_group_id is not None and clip["group_id"] != previous_group_id:
            lines.append("")
        previous_group_id = clip["group_id"]
        for utterance in clip["utterances"]:
            moment = (clip_start(clip) + timedelta(seconds=utterance["start_seconds"])).astimezone()
            lines.append(f"[{moment.strftime(constants.TRANSCRIPT_TIME_FORMAT)}] {utterance['text']}")
    return "\n".join(lines) + ("\n" if lines else "")
