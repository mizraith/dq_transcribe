"""Read a Meet Manager report saved as HTML.

Hy-Tek's HTML reports are usually the printed report inside a ``<pre>`` block;
some are tables. Both are turned into text lines (a table row becomes one line,
its cells separated by spaces) and read by the shared report parser.
"""

from __future__ import annotations

import html
from html.parser import HTMLParser
from pathlib import Path

from dq_transcribe.meet_files.model import MeetProgram
from dq_transcribe.meet_files.report_text import parse_report_text

# Tags that end a printed line.
_LINE_BREAK_TAGS = frozenset({"br", "p", "div", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "li", "table", "pre"})
_CELL_TAGS = frozenset({"td", "th"})
_SKIPPED_TAGS = frozenset({"script", "style", "head", "title"})
CELL_SEPARATOR = "   "
TEXT_ENCODINGS = ("utf-8", "cp1252", "latin-1")


class _TextCollector(HTMLParser):
    """Collect an HTML page's visible text as printed lines."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0
        self._in_pre = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIPPED_TAGS:
            self._skip_depth += 1
        elif tag in _CELL_TAGS:
            self.parts.append(CELL_SEPARATOR)
        elif tag in _LINE_BREAK_TAGS:
            self.parts.append("\n")
        if tag == "pre":
            self._in_pre += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in _LINE_BREAK_TAGS:
            self.parts.append("\n")
        if tag == "pre":
            self._in_pre = max(0, self._in_pre - 1)

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        self.parts.append(data if self._in_pre else " ".join(data.split()) if data.strip() else "")


def html_text(markup: str) -> str:
    """The visible text of an HTML report, one printed line per line."""
    collector = _TextCollector()
    collector.feed(markup)
    return html.unescape("".join(collector.parts))


def read_html_report(path: Path) -> MeetProgram:
    """Read events, heats and entries from an HTML report."""
    raw = path.read_bytes()
    return parse_report_text(html_text(_decode(raw)))


def read_text_report(path: Path) -> MeetProgram:
    """Read a report saved as plain text."""
    return parse_report_text(_decode(path.read_bytes()))


def _decode(raw: bytes) -> str:
    """Decode a report, trying the encodings Meet Manager is known to write (Windows)."""
    for encoding in TEXT_ENCODINGS:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode(TEXT_ENCODINGS[-1], errors="replace")
