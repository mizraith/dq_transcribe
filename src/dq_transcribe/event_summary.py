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
PICKER_TEMPLATE_PATH = Path(__file__).parent / constants.WEB_DIRECTORY_NAME / constants.EVENT_PICKER_FILENAME
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
COLUMNS = ("Heat", "Lane", "Swimmer", "Club", "Code", "Infraction", "Official")
STATUS_COLUMN = "Status"
ENTERED_COLUMN = "Entered"
HEAD_HTML = "<tr>" + "".join(f"<th>{name}</th>" for name in (*COLUMNS, ENTERED_COLUMN)) + "</tr>"
HEAD_WITH_STATUS_HTML = "<tr>" + "".join(f"<th>{name}</th>" for name in (*COLUMNS, STATUS_COLUMN, ENTERED_COLUMN)) + "</tr>"
HEADING_FORMAT = "Event {event} DQs ({count})"
ALL_TITLE_FORMAT = "Event {event}: all DQs ({count})"
ALL_NONE_TEXT = "No DQs in this event."
ALL_NOTE = "Every DQ of the event, whatever its status. Enter only Notified and Upheld DQs in Meet Manager."
PICKER_TITLE = "Print DQ summary for event"


def _escape(value: Any) -> str:
    """Text made safe for HTML."""
    return html.escape("" if value is None else str(value))


def infraction_code_text(infraction: dict[str, Any]) -> str:
    """The code to enter: "3J", or the codes it could be when not settled yet ("1J / 3J ?")."""
    if infraction.get("code"):
        return infraction["code"]
    options = infraction.get("code_options") or []
    return CODE_OPTION_SEPARATOR.join(options) + UNSURE_MARK if options else UNKNOWN_CODE


def _row(dq: dict[str, Any], css_class: str = "", with_status: bool = False) -> str:
    """One table row: heat, lane, swimmer, club, then each infraction on its own line
    (code and description side by side), official and the entered box.

    A DQ can carry several infractions, and an infraction whose code is not settled
    lists every code it could be: the operator picks the one to enter.
    ``with_status`` adds the DQ's status ("Incomplete", "Declined", ...) after the official.
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
        f"<td class=\"what\">{descriptions}</td><td>{_escape(dq.get('official'))}</td>"
        + (f'<td class="status status-{_escape(dq.get("status"))}">{_escape(status_label(dq))}</td>' if with_status else "")
        + "<td class=\"box\">\u2610</td></tr>"
    )


def status_label(dq: dict[str, Any]) -> str:
    """The DQ's status as the DQ list shows it ("Pending notification")."""
    return constants.DQ_STATUS_LABELS.get(dq.get("status") or "", dq.get("status") or "")


def render_event_summary(
    meet_name: str, event: str, dqs: list[dict[str, Any]], printed_at: datetime | None = None, all_statuses: bool = False
) -> bytes:
    """The printable summary page for one event.

    Args:
        meet_name: The meet's name (page header).
        event: The event number.
        dqs: The event's DQs as ``DqStore.list_dqs`` returns them (sorted by heat and lane).
        printed_at: When printed (default now).
        all_statuses: Every DQ of the event whatever its status (Called, Incomplete,
            Declined, ...), with a Status column: the Admin Assistant's Reports
            printout, for working "blind" from paper. Otherwise only the DQs to enter
            in Meet Manager (the version offered at Notify event).
    """
    if all_statuses:
        return _render_all_statuses(meet_name, event, dqs, printed_at)
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
        heading=_escape(HEADING_FORMAT.format(event=event, count=len(to_enter))),
        meet_name=_escape(meet_name),
        event=_escape(event),
        event_label=_escape(label),
        count=str(len(to_enter)),
        head=HEAD_HTML,
        rows=rows,
        overturned=overturned_html,
        pending=pending_html,
        printed=_escape((printed_at or datetime.now()).strftime(PRINTED_FORMAT)),
        app_name=_escape(constants.APP_DISPLAY_NAME),
    ).encode("utf-8")


def _render_all_statuses(meet_name: str, event: str, dqs: list[dict[str, Any]], printed_at: datetime | None) -> bytes:
    """Every DQ of the event in heat and lane order, with its status (see ``render_event_summary``)."""
    label = next((dq.get("event_label") for dq in dqs if dq.get("event_label")), "")
    columns = len(COLUMNS) + 2
    rows = "".join(
        _row(dq, "struck" if dq["state"] in (constants.DQ_STATE_OVERTURNED, constants.DQ_STATE_DECLINED) else "", with_status=True)
        for dq in dqs
    ) or f'<tr><td colspan="{columns}" class="none">{_escape(ALL_NONE_TEXT)}</td></tr>'
    template = string.Template(SUMMARY_TEMPLATE_PATH.read_text("utf-8"))
    return template.substitute(
        title=_escape(TITLE_FORMAT.format(event=event)),
        heading=_escape(ALL_TITLE_FORMAT.format(event=event, count=len(dqs))),
        meet_name=_escape(meet_name),
        event=_escape(event),
        event_label=_escape(label),
        count=str(len(dqs)),
        head=HEAD_WITH_STATUS_HTML,
        rows=rows,
        overturned="",
        pending=f'<p class="all-note">{_escape(ALL_NOTE)}</p>',
        printed=_escape((printed_at or datetime.now()).strftime(PRINTED_FORMAT)),
        app_name=_escape(constants.APP_DISPLAY_NAME),
    ).encode("utf-8")


def render_event_picker(meet_name: str, events: list[tuple[str, str, int]], hidden_fields: dict[str, str]) -> bytes:
    """The "Print DQ summary for event ___" page: a number box, and a button per event with DQs.

    Args:
        meet_name: The meet's name.
        events: ``(event number, event label, DQ count)`` for the events that have DQs.
        hidden_fields: Query values to keep (the meet, "all statuses").
    """
    hidden = "".join(f'<input type="hidden" name="{_escape(key)}" value="{_escape(value)}">' for key, value in hidden_fields.items())
    buttons = "".join(
        f'<button type="submit" name="{constants.QUERY_KEY_EVENT}" value="{_escape(number)}">Event {_escape(number)}'
        f'<small>{_escape(label)} \u00b7 {count} DQ{"s" if count != 1 else ""}</small></button>'
        for number, label, count in events
    ) or "<p>No DQs yet in this meet.</p>"
    template = string.Template(PICKER_TEMPLATE_PATH.read_text("utf-8"))
    return template.substitute(
        title=_escape(PICKER_TITLE), meet_name=_escape(meet_name), route=constants.ROUTE_EVENT_SUMMARY,
        event_key=constants.QUERY_KEY_EVENT, hidden=hidden, buttons=buttons,
    ).encode("utf-8")
