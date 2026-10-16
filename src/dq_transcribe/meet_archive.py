"""The meet archive: one zip with everything needed to trace a meet's DQs later.

The owner keeps meet data for at least a year, with a copy for the meet host.
The archive holds:

* ``README.txt``: the meet, when the archive was made, what is inside.
* ``dqs.csv`` and ``dq_history.csv``: every DQ (one row each) and every state
  change (notified, protested, ruled ...), for a spreadsheet.
* ``dqs.json``: the same DQs with everything the app stores.
* ``summary.html``: DQs by event, and the protest history, to read or print.
* ``slips.html``: the filled-in slips of every DQ that was not declined.
* ``transcript.txt`` and ``clips.json``: every radio turn heard at the meet.
* ``audio/``: every clip's audio (WAV), in the meet's day folders.

**Not included:** the Hy-Tek Meet Manager files (heat sheets, database). The
meet's own computer already keeps them, so they are not saved twice.
"""

from __future__ import annotations

import csv
import html
import io
import json
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from dq_transcribe import constants
from dq_transcribe.database import Database
from dq_transcribe.dq_store import DqStore
from dq_transcribe.slip_page import render_slips
from dq_transcribe.transcript import format_transcript_text

ARCHIVE_NAME_FORMAT = "{folder}_archive_{stamp}.zip"
ARCHIVE_STAMP_FORMAT = "%Y%m%d_%H%M"
AUDIO_FOLDER = "audio"
LOCAL_TIME_FORMAT = "%m/%d/%Y %I:%M %p"
DQ_COLUMNS = (
    "id", "event", "heat", "lane", "relay_leg", "swimmer", "club", "infractions", "codes", "official",
    "official_role", "chief_judge", "referee", "status", "call_time", "notified_at", "notified_by",
    "protest_count", "protested_at", "ruled_by", "notes",
)
HISTORY_COLUMNS = ("dq_id", "event", "heat", "lane", "at", "from_state", "to_state", "by", "note")
README_TEXT = """{meet_name}
First day: {start_date}
Archive made: {made_at} by {app}

Contents
  dqs.csv           one row per DQ ({dq_count} DQs)
  dq_history.csv    every state change: accepted, notified, protested, ruling
  dqs.json          the DQs with everything the app stores
  summary.html      DQs by event and the protest history (open in a browser)
  slips.html        the filled-in DQ slips (open in a browser to print)
  transcript.txt    every radio turn heard ({clip_count} clips)
  clips.json        the clips and turns with their timing
  audio/            the audio of every clip (WAV)

Not included: the Hy-Tek Meet Manager files. The meet's own computer keeps them.
Times are local ({timezone}).
"""


def _local(text: str | None) -> str:
    """An ISO time as local 12-hour text ("" if missing)."""
    if not text:
        return ""
    try:
        return datetime.fromisoformat(text).astimezone().strftime(LOCAL_TIME_FORMAT)
    except ValueError:
        return text


def _dq_rows(dqs: list[dict[str, Any]]) -> list[list[Any]]:
    """dqs.csv rows."""
    rows = []
    for dq in dqs:
        values = {
            **dq,
            "infractions": "; ".join(item["description"] for item in dq["infractions"]),
            "codes": "; ".join(item["code"] or "" for item in dq["infractions"]),
            "status": constants.DQ_STATUS_LABELS.get(dq["status"], dq["status"]),
            "call_time": _local(dq.get("call_time")),
            "notified_at": _local(dq.get("notified_at")),
            "protested_at": _local(dq.get("protested_at")),
        }
        rows.append([values.get(column) if values.get(column) is not None else "" for column in DQ_COLUMNS])
    return rows


def _csv_text(header: tuple[str, ...], rows: list[list[Any]]) -> str:
    """CSV text with a header row."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue()


def _summary_html(meet: dict[str, Any], dqs: list[dict[str, Any]]) -> str:
    """DQs by event, then every protest and ruling."""
    escape = html.escape
    parts = [
        f"<!doctype html><html><head><meta charset='utf-8'><title>{escape(meet['name'])} DQ summary</title>",
        "<style>body{font-family:Arial,sans-serif;margin:1.5rem}table{border-collapse:collapse;width:100%;margin-bottom:1.2rem}"
        "td,th{border:1px solid #ccc;padding:0.3rem 0.5rem;text-align:left;font-size:0.9rem}th{background:#f3f4f6}</style></head><body>",
        f"<h1>{escape(meet['name'])}</h1><p>First day {escape(meet['start_date'])} · {len(dqs)} DQs</p>",
    ]
    events = sorted({dq["event"] or "" for dq in dqs}, key=lambda value: (len(value), value))
    for event in events:
        parts.append(f"<h2>Event {escape(event or '?')}</h2><table><tr><th>Heat</th><th>Lane</th><th>Swimmer</th><th>Team</th>"
                     "<th>Infraction</th><th>Status</th><th>Notified</th><th>Protests</th></tr>")
        for dq in (item for item in dqs if (item["event"] or "") == event):
            infractions = "; ".join(f"{item['code'] or '—'} {item['description']}" for item in dq["infractions"])
            parts.append(
                f"<tr><td>{escape(dq['heat'] or '')}</td><td>{escape(dq['lane'] or '')}</td><td>{escape(dq['swimmer'] or '')}</td>"
                f"<td>{escape(dq['club'] or '')}</td><td>{escape(infractions)}</td>"
                f"<td>{escape(constants.DQ_STATUS_LABELS.get(dq['status'], dq['status']))}</td>"
                f"<td>{escape(_local(dq.get('notified_at')))} {escape(dq.get('notified_by') or '')}</td>"
                f"<td>{dq.get('protest_count') or 0}</td></tr>"
            )
        parts.append("</table>")
    protests = [(dq, item) for dq in dqs for item in dq["history"]
                if item["to_state"] in (constants.DQ_STATE_PROTESTED, constants.DQ_STATE_UPHELD, constants.DQ_STATE_OVERTURNED)]
    parts.append("<h2>Protest history</h2>")
    if protests:
        parts.append("<table><tr><th>When</th><th>Event/Heat/Lane</th><th>Swimmer</th><th>What</th><th>By</th><th>Note</th></tr>")
        for dq, item in protests:
            parts.append(
                f"<tr><td>{escape(_local(item['at']))}</td><td>{escape(dq['event'] or '?')}/{escape(dq['heat'] or '?')}/{escape(dq['lane'] or '?')}</td>"
                f"<td>{escape(dq['swimmer'] or '')}</td><td>{escape(item['to_state'])}</td><td>{escape(item['by_name'] or '')}</td>"
                f"<td>{escape(item['note'] or '')}</td></tr>"
            )
        parts.append("</table>")
    else:
        parts.append("<p>No protests.</p>")
    parts.append("</body></html>")
    return "".join(parts)


def archive_filename(meet: dict[str, Any], folder_name: str, now: datetime | None = None) -> str:
    """"2026-10-16_candy-meet_archive_20261016_2130.zip"."""
    return ARCHIVE_NAME_FORMAT.format(folder=folder_name, stamp=(now or datetime.now()).strftime(ARCHIVE_STAMP_FORMAT))


def build_meet_archive(
    database: Database, dq_store: DqStore, meet_id: int, recordings_directory: Path, destination: Path
) -> dict[str, int]:
    """Write a meet's archive zip.

    Args:
        database: The app database.
        dq_store: The DQ store.
        meet_id: The meet to archive.
        recordings_directory: Where clip audio is stored.
        destination: The zip file to write.

    Returns:
        Counts: ``dqs``, ``clips``, ``audio_files``.
    """
    meet = database.get_meet(meet_id)
    if meet is None:
        raise ValueError(f"No meet {meet_id}")
    dqs = dq_store.list_dqs(meet_id)
    clips = database.list_clips(newest_first=False, meet_id=meet_id)
    history_rows = [
        [dq["id"], dq["event"] or "", dq["heat"] or "", dq["lane"] or "", _local(item["at"]), item["from_state"] or "",
         item["to_state"], item["by_name"] or "", item["note"] or ""]
        for dq in dqs for item in dq["history"]
    ]
    audio_files = 0
    base = recordings_directory.resolve()
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("README.txt", README_TEXT.format(
            meet_name=meet["name"], start_date=meet["start_date"], made_at=datetime.now().strftime(LOCAL_TIME_FORMAT),
            app=constants.APP_NAME, dq_count=len(dqs), clip_count=len(clips),
            timezone=datetime.now().astimezone().tzname(),
        ))
        archive.writestr("dqs.csv", _csv_text(DQ_COLUMNS, _dq_rows(dqs)))
        archive.writestr("dq_history.csv", _csv_text(HISTORY_COLUMNS, history_rows))
        archive.writestr("dqs.json", json.dumps(dqs, indent=2))
        archive.writestr("summary.html", _summary_html(meet, dqs))
        live = [dq for dq in dqs if dq["state"] != constants.DQ_STATE_DECLINED]
        archive.writestr("slips.html", render_slips(live, f"{meet['name']} DQ slips").decode("utf-8"))
        archive.writestr("transcript.txt", format_transcript_text(clips))
        archive.writestr("clips.json", json.dumps(clips, indent=2))
        for clip in clips:
            audio_path = (base / clip["audio_filename"]).resolve()
            if audio_path.is_relative_to(base) and audio_path.is_file():
                # Audio does not compress: store it as is (faster on the tablet).
                archive.write(audio_path, f"{AUDIO_FOLDER}/{clip['audio_filename']}", compress_type=zipfile.ZIP_STORED)
                audio_files += 1
    return {"dqs": len(dqs), "clips": len(clips), "audio_files": audio_files}
