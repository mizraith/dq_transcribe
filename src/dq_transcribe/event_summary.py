"""The printed DQ summary for one event, for the Meet Manager computer operator.

Offered when an event is notified (owner, 2026-10-15): the operator types each
DQ's code into Hy-Tek Meet Manager and invalidates the time. So the page lists,
in heat and lane order and in large type, exactly what that takes: heat, lane,
swimmer (or relay), club, the DQ code(s) and description, the official and an
"entered" box to tick on paper.

* Overturned DQs are listed apart, struck through: **not** to be entered (or to
  be removed if they already were).
* DQs of the event not yet notified (Called, Incomplete, Pending notification)
  are counted at the bottom, so the operator knows the event may still change.
  Declined DQs are left out.

Printing is a stopgap the owner hopes to retire; the app never touches the Meet
Manager database itself.
"""

from __future__ import annotations

import html
import string
from datetime import datetime
from pathlib import Path
from typing import Any

from dq_transcribe import constants

SUMMARY_TEMPLATE_PATH = Path(__file__).parent / constants.WEB_DIRECTORY_NAME / constants.EVENT_SUMMARY_FILENAME
TITLE_FORMAT = "DQ summary, event {event}"
PRINTED_FORMAT = "%m/%d/%Y %I:%M %p"
CODE_OPTION_SEPARATOR = " / "
UNSURE_MARK = " ?"
UNKNOWN_CODE = "?"
RELAY_LEG_FORMAT = "{swimmer} (swimmer {leg})"
PENDING_FORMAT = "{count} more DQ(s) in this event not notified yet: this summary may change."
NONE_TEXT = "No notified DQs in this event."
# States listed as DQs to enter, and as overturned (not to enter).
ENTER_STATES = (constants.DQ_STATE_NOTIFIED, constants.DQ_STATE_PROTESTED, constants.DQ_STATE_UPHELD)
PROTESTED_NOTE = "protest pending"
NOT_YET_NOTIFIED_STATES = (constants.DQ_STATE_CALLED, constants.DQ_STATE_ACCEPTED)


def _escape(value: Any) -> str:
    """Text made safe for HTML."""
    return html.escape("" if value is None else str(value))


def infraction_code_text(infraction: dict[str, Any]) -> str:
    """The code to enter: "3J", or the codes it could be when not settled yet ("1J / 3J ?")."""
    if infraction.get("code"):
        return infraction["code"]
    options = infraction.get("code_options") or []
    return CODE_OPTION_SEPARATOR.join(options) + UNSURE_MARK if options else UNKNOWN_CODE


def _row(dq: dict[str, Any], css_class: str = "") -> str:
    """One table row: heat, lane, swimmer, club, then each infraction on its own line
    (code and description side by side), official and the entered box.

    A DQ can carry several infractions, and an infraction whose code is not settled
    lists every code it could be: the operator picks the one to enter.
    """
    swimmer = dq.get("swimmer") or ""
    if dq.get("relay_leg"):
        swimmer = RELAY_LEG_FORMAT.format(swimmer=swimmer, leg=dq["relay_leg"])
    infractions = dq["infractions"] or [{"description": "", "code": None}]
    codes = "".join(
        f'<div class="{"unsure" if not item.get("code") else ""}">{_escape(infraction_code_text(item))}</div>' for item in infractions
    )
    descriptions = "".join(f"<div>{_escape(item['description'])}</div>" for item in infractions)
    if dq["state"] == constants.DQ_STATE_PROTESTED:
        descriptions += f'<div class="note">({_escape(PROTESTED_NOTE)})</div>'
    return (
        f'<tr class="{css_class}"><td class="num">{_escape(dq.get("heat"))}</td><td class="num">{_escape(dq.get("lane"))}</td>'
        f"<td>{_escape(swimmer)}</td><td>{_escape(dq.get('club'))}</td><td class=\"code\">{codes}</td>"
        f"<td class=\"what\">{descriptions}</td><td>{_escape(dq.get('official'))}</td><td class=\"box\">\u2610</td></tr>"
    )


def render_event_summary(meet_name: str, event: str, dqs: list[dict[str, Any]], printed_at: datetime | None = None) -> bytes:
    """The printable summary page for one event.

    Args:
        meet_name: The meet's name (page header).
        event: The event number.
        dqs: The event's DQs as ``DqStore.list_dqs`` returns them (sorted by heat and lane).
        printed_at: When printed (default now).
    """
    to_enter = [dq for dq in dqs if dq["state"] in ENTER_STATES]
    overturned = [dq for dq in dqs if dq["state"] == constants.DQ_STATE_OVERTURNED]
    pending = [dq for dq in dqs if dq["state"] in NOT_YET_NOTIFIED_STATES]
    label = next((dq.get("event_label") for dq in dqs if dq.get("event_label")), "")
    rows = "".join(_row(dq) for dq in to_enter) or f'<tr><td colspan="8" class="none">{_escape(NONE_TEXT)}</td></tr>'
    overturned_html = ""
    if overturned:
        overturned_html = (
            '<h2>Overturned: do NOT enter (remove if already entered)</h2><table class="overturned"><tbody>'
            + "".join(_row(dq, "struck") for dq in overturned)
            + "</tbody></table>"
        )
    pending_html = f'<p class="pending">{_escape(PENDING_FORMAT.format(count=len(pending)))}</p>' if pending else ""
    template = string.Template(SUMMARY_TEMPLATE_PATH.read_text("utf-8"))
    return template.substitute(
        title=_escape(TITLE_FORMAT.format(event=event)),
        meet_name=_escape(meet_name),
        event=_escape(event),
        event_label=_escape(label),
        count=str(len(to_enter)),
        rows=rows,
        overturned=overturned_html,
        pending=pending_html,
        printed=_escape((printed_at or datetime.now()).strftime(PRINTED_FORMAT)),
        app_name=_escape(constants.APP_NAME),
    ).encode("utf-8")
