"""Printable DQ slips: each DQ filled in on a copy of the paper slip's layout.

The layout is built from the slip's code table (``reference/dq_codes``), so it
follows the revision in use: sections in printed order, each with its START /
SWIM / TURN / FINISH blanks where the slip has them, and every coded line with
its blank. The DQ's infractions are marked with an X in their blank (plus the
turn number or other detail where the line asks for one), the phases of each
section are marked, and the judge, chief judge (initials) and referee are
written in a script font.

Infractions without a slip code are written on the "Other" line of their
section (or the Miscellaneous "Other" line), so nothing on the DQ is lost.

Printing is one of the ways to notify; the owner prefers paperless notification.
"""

from __future__ import annotations

import html
import json
import string
from datetime import datetime
from pathlib import Path
from typing import Any

from dq_transcribe import constants
from dq_transcribe.dq_store import number_sort_key
from dq_transcribe.slip_codes import load_dq_codes

SLIP_TITLE = "Disqualification Report"
COPY_LABEL = "Coach copy"
CHOSEN_MARK = "X"
FREE_TEXT_FIELD = "free_text"
YES = "yes"
MISCELLANEOUS_SECTION = "Miscellaneous"
OTHER_DESCRIPTION = "Other"
DETAIL_SEPARATOR = " "
REVISION_LABEL_FORMAT = "rev. ({month}/{year:02d})"
PRINTED_FORMAT = "%m/%d/%Y %I:%M %p"
SLIP_TEMPLATE_PATH = Path(__file__).parent / constants.WEB_DIRECTORY_NAME / constants.SLIP_PAGE_FILENAME
NOTIFIED_TIME_FORMAT = constants.CLOCK_FORMAT_12_HOUR


def revision_label(revision: str) -> str:
    """"2024-01" -> "rev. (1/24)", as printed on the slip."""
    try:
        year, month = (int(part) for part in revision.split("-"))
    except ValueError:
        return f"rev. {revision}"
    return REVISION_LABEL_FORMAT.format(month=month, year=year % 100)


def initials(name: str | None) -> str:
    """"Lee Chan" -> "LC" (the chief judge initials the slip)."""
    return "".join(part[0].upper() for part in (name or "").split() if part[0].isalpha())


def _escape(value: Any) -> str:
    """Text made safe for HTML."""
    return html.escape("" if value is None else str(value))


def _blank(value: Any = "", css_class: str = "") -> str:
    """A fill-in blank, with its value (if any) written in."""
    return f'<span class="blank {css_class}">{_escape(value)}</span>'


def _section_rows(code_rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    """The slip's lines by section, in printed order."""
    sections: dict[str, list[dict[str, str]]] = {}
    for row in code_rows:
        sections.setdefault(row["section"], []).append(row)
    return sections


def _place_infractions(dq: dict[str, Any], sections: dict[str, list[dict[str, str]]]) -> tuple[dict[str, str], dict[str, list[str]], dict[str, set[str]]]:
    """Work out what to write where.

    Returns:
        ``marks``: code -> text for its blank ("X", or "X 3" with a turn number),
        ``other_text``: section -> descriptions for its "Other" line,
        ``phases``: section -> race phases to mark.
    """
    code_to_section = {row["code"]: section for section, rows in sections.items() for row in rows if row["code"]}
    free_text_codes = {row["code"] for rows in sections.values() for row in rows if row["detail_field"] == FREE_TEXT_FIELD}
    marks: dict[str, str] = {}
    other_text: dict[str, list[str]] = {}
    phases: dict[str, set[str]] = {}
    for infraction in dq["infractions"]:
        code = infraction.get("code")
        section = code_to_section.get(code or "")
        if section is None:
            other_text.setdefault(MISCELLANEOUS_SECTION, []).append(infraction["description"])
            continue
        phases.setdefault(section, set()).update(infraction.get("phases") or [])
        if code in free_text_codes:
            other_text.setdefault(section, []).append(infraction.get("detail") or infraction["description"])
            continue
        detail = infraction.get("detail") or ""
        marks[code] = CHOSEN_MARK + (DETAIL_SEPARATOR + detail if detail else "")
    return marks, other_text, phases


def _render_section(section: str, rows: list[dict[str, str]], marks: dict[str, str], other_text: list[str], phases: set[str]) -> str:
    """One section of the slip (title, phase blanks, and its lines)."""
    parts = ['<div class="section">', '<div class="row">', f'<span class="section-title">{_escape(section.upper())}</span>']
    if rows and rows[0].get("slip_has_phase_boxes") == YES:
        for phase in constants.RACE_PHASES:
            parts.append(f'<span class="item">{_escape(phase.upper())}{_blank(CHOSEN_MARK if phase in phases else "", "phase")}</span>')
    parts.append("</div>")
    current_group = None
    line: list[str] = []

    def flush() -> None:
        if line:
            parts.append('<div class="row">' + "".join(line) + "</div>")
            line.clear()

    for row in rows:
        if row["detail_field"] == FREE_TEXT_FIELD:
            flush()
            code = f'({row["code"]})' if row["code"] else ""
            parts.append(f'<div class="row"><span>{_escape(row["description"].upper())}{_escape(code)}:</span>'
                         f'{_blank("; ".join(other_text), "full")}</div>')
            current_group = None
            continue
        if row["group"] != current_group:
            flush()
            current_group = row["group"]
            if current_group:
                line.append(f'<span class="group-label">{_escape(current_group.upper())}:</span>')
        code = row["code"]
        mark = marks.get(code, "") if code else ""
        label = _escape(row["description"]) + (f"({_escape(code)})" if code else "")
        chosen = " chosen" if mark else ""
        line.append(f'<span class="item{chosen}">{label} {_blank(mark)}</span>')
    flush()
    if MISCELLANEOUS_SECTION == section and other_text and not any(row["detail_field"] == FREE_TEXT_FIELD for row in rows):
        parts.append(f'<div class="row">{_blank("; ".join(other_text), "full")}</div>')
    parts.append("</div>")
    return "".join(parts)


def slip_referee(dq: dict[str, Any]) -> str | None:
    """The referee written on the slip: the DQ's referee, or the official when a referee made the call."""
    if dq.get("referee"):
        return dq["referee"]
    return dq.get("official") if dq.get("official_role") in constants.REFEREE_ROLES else None


def render_slip(dq: dict[str, Any], code_rows: list[dict[str, str]], revision: str, printed_at: datetime) -> str:
    """One filled-in slip as HTML."""
    sections = _section_rows(code_rows)
    marks, other_text, phases = _place_infractions(dq, sections)
    swimmer = dq.get("swimmer") or ""
    if dq.get("relay_leg"):
        swimmer = f"{swimmer} (swimmer {dq['relay_leg']})"
    parts = [
        '<section class="slip">',
        f"<h1>{_escape(SLIP_TITLE.upper())}</h1>",
        f'<div class="row header-row"><span>EVENT#{_blank(dq.get("event"), "wide big")}</span><span>HEAT{_blank(dq.get("heat"), "wide big")}</span>'
        f'<span>LANE{_blank(dq.get("lane"), "wide big")}</span></div>',
        f'<div class="row header-row"><span>SWIMMER</span>{_blank(swimmer, "full big")}<span>TEAM{_blank(dq.get("club"), "wide big")}</span></div>',
    ]
    for section, rows in sections.items():
        parts.append(_render_section(section, rows, marks, other_text.get(section, []), phases.get(section, set())))
    notified_at = dq.get("notified_at")
    notified_text = datetime.fromisoformat(notified_at).astimezone().strftime(NOTIFIED_TIME_FORMAT).lstrip("0") if notified_at else ""
    parts += [
        f'<div class="row" style="margin-top:0.15in"><span>JUDGE:</span>{_blank(dq.get("official"), "full name")}'
        f'<span>CJ:{_blank(initials(dq.get("chief_judge")), "name")}</span></div>',
        f'<div class="row"><span>REFEREE:</span>{_blank(slip_referee(dq), "full name")}</div>',
        f'<div class="row"><span>NOTIFIED:</span>{_blank("")}<span>SWIMMER</span>{_blank(notified_text, "wide")}<span>COACH</span></div>',
        f'<div class="footer"><span>{_escape(revision_label(revision))} · printed {_escape(printed_at.strftime(PRINTED_FORMAT))} by {constants.APP_NAME}</span>'
        f'<span class="copy">{_escape(COPY_LABEL.upper())}</span></div>',
        "</section>",
    ]
    return "".join(parts)


PRINT_TOOLBAR_FORMAT = '<div class="toolbar"><button type="button" onclick="window.print()">Print</button><span>{text}</span></div>'
BACK_TOOLBAR_FORMAT = '<div class="toolbar"><a href="{url}">\u2190 {label}</a></div>'
PRINT_HINT_FORMAT = "{count} slip(s) \u00b7 {revision} \u00b7 {layout} \u00b7 tap Print, or use the browser's Share > Print"
LAYOUT_LABELS = {constants.SLIP_LAYOUT_ONE_PER_PAGE: "one per page", constants.SLIP_LAYOUT_TWO_UP: "2 per page"}
SLIPS_PER_SHEET = 2


def back_toolbar(url: str, label: str) -> str:
    """A toolbar with a back link in place of the Print button (the coach page on a phone)."""
    return BACK_TOOLBAR_FORMAT.format(url=_escape(url), label=_escape(label))


def print_hint(count: int, revision: str, layout: str) -> str:
    """"3 slip(s) · rev. (1/24) · 2 per page · tap Print ..." (escaped)."""
    return _escape(PRINT_HINT_FORMAT.format(count=count, revision=revision_label(revision), layout=LAYOUT_LABELS[layout]))


def club_sort_key(dq: dict[str, Any]) -> tuple[str, Any, Any, Any]:
    """Sort slips by club, then event, heat and lane (coaches pick up their club's pile)."""
    return ((dq.get("club") or "\uffff").lower(), number_sort_key(dq.get("event")), number_sort_key(dq.get("heat")), number_sort_key(dq.get("lane")))


# The toolbar for printing coaches' requested slips: Print, and clear the requests once printed.
# Printing (the browser's "afterprint") clears them by itself; "Mark printed" does it by hand,
# and Undo puts them back. A string.Template: the script must not contain a dollar sign.
PRINT_REQUESTS_TOOLBAR = string.Template(
    '<div class="toolbar"><button type="button" onclick="window.print()">Print</button>'
    '<button type="button" class="secondary" id="mark-printed">Mark printed</button>'
    '<span id="print-request-status">$hint</span></div>'
    """<script>
"use strict";
(() => {
  const ids = $ids;
  const status = document.getElementById("print-request-status");
  const markButton = document.getElementById("mark-printed");
  let cleared = false;
  async function setRequested(requested) {
    const body = {};
    body[$ids_key] = ids;
    body[$requested_key] = requested;
    const response = await fetch($route, { method: "POST", headers: { "Content-Type": $json_type }, body: JSON.stringify(body) });
    if (!response.ok) {
      throw new Error("server answered " + response.status);
    }
  }
  async function markPrinted() {
    if (cleared || !ids.length) {
      return;
    }
    cleared = true;
    try {
      await setRequested(false);
      status.textContent = "";
      status.append(Object.assign(document.createElement("span"), { className: "done", textContent: "\\u2713 Print requests cleared " }));
      const undo = Object.assign(document.createElement("button"), { type: "button", className: "secondary", textContent: "Undo" });
      undo.addEventListener("click", async () => {
        await setRequested(true);
        cleared = false;
        status.textContent = "Print requests restored.";
      });
      status.append(undo);
    } catch (error) {
      cleared = false;
      status.textContent = "Could not clear the print requests: " + error.message;
    }
  }
  markButton.addEventListener("click", markPrinted);
  window.addEventListener("afterprint", markPrinted);
})();
</script>"""
)


def print_requests_toolbar(dq_ids: list[int], revision: str, layout: str) -> str:
    """The toolbar for the coaches' requested slips (see ``PRINT_REQUESTS_TOOLBAR``)."""
    return PRINT_REQUESTS_TOOLBAR.substitute(
        hint=print_hint(len(dq_ids), revision, layout),
        ids=json.dumps(dq_ids),
        ids_key=json.dumps(constants.REQUEST_KEY_DQ_IDS),
        requested_key=json.dumps(constants.REQUEST_KEY_REQUESTED),
        route=json.dumps(constants.ROUTE_DQ_PRINT_REQUESTS),
        json_type=json.dumps(constants.JSON_CONTENT_TYPE),
    )


def render_slips(
    dqs: list[dict[str, Any]],
    title: str,
    revision: str = constants.CURRENT_SLIP_REVISION,
    toolbar_html: str | None = None,
    layout: str = constants.SLIP_LAYOUT_ONE_PER_PAGE,
    after_html: str = "",
) -> bytes:
    """A page of filled-in slips.

    Args:
        dqs: DQs as returned by ``DqStore.list_dqs``, in printing order.
        title: The page title (shown in the browser tab and print header).
        revision: Slip revision whose layout to use.
        toolbar_html: The toolbar (default: a Print button with a hint). The coach
            page passes ``back_toolbar(...)``.
        layout: ``constants.SLIP_LAYOUT_ONE_PER_PAGE``, or ``SLIP_LAYOUT_TWO_UP``
            (two slips side by side on a portrait page).
        after_html: Trusted HTML shown after the slips (the coach page's
            "Request a printout" form); never printed.
    """
    if layout not in constants.SLIP_LAYOUTS:
        layout = constants.SLIP_LAYOUT_ONE_PER_PAGE
    code_rows = load_dq_codes(revision)
    printed_at = datetime.now()
    rendered = [render_slip(dq, code_rows, revision, printed_at) for dq in dqs]
    if layout == constants.SLIP_LAYOUT_TWO_UP:
        slips = "".join(
            '<div class="sheet">' + "".join(rendered[index:index + SLIPS_PER_SHEET]) + "</div>"
            for index in range(0, len(rendered), SLIPS_PER_SHEET)
        )
    else:
        slips = "".join(rendered)
    if not dqs:
        slips = '<p style="padding:1rem">No DQs to print.</p>'
    template = string.Template(SLIP_TEMPLATE_PATH.read_text("utf-8"))
    return template.substitute(
        title=_escape(title),
        font_url=constants.ROUTE_FONTS + constants.SLIP_FONT_FILENAME,
        layout_class=layout.replace("_", "-"),
        toolbar=toolbar_html if toolbar_html is not None else PRINT_TOOLBAR_FORMAT.format(text=print_hint(len(dqs), revision, layout)),
        slips=slips,
        after=after_html,
    ).encode("utf-8")
