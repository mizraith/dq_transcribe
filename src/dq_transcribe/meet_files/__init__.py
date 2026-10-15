"""Meet Manager files: read a heat sheet, report or database into a meet program.

Usage::

    program, file_format = read_meet_file(path)

The format is worked out from the file's content (and its name as a hint): a
Hy-Tek Meet Manager backup or database, a PDF report, an HTML report, or plain text.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from dq_transcribe import constants
from dq_transcribe.meet_files.errors import MeetFileError
from dq_transcribe.meet_files.html_report import read_html_report, read_text_report
from dq_transcribe.meet_files.mm_database import DATABASE_EXTENSIONS, read_meet_manager_database
from dq_transcribe.meet_files.model import MeetProgram
from dq_transcribe.meet_files.pdf_report import read_pdf_report

__all__ = ["MeetFileError", "MeetProgram", "detect_format", "read_meet_file"]

PDF_SIGNATURE = b"%PDF"
# Access databases start with this, then "Standard Jet DB" or "Standard ACE DB".
ACCESS_SIGNATURE_OFFSET = 4
ACCESS_SIGNATURE = b"Standard "
HTML_MARKERS = (b"<html", b"<!doctype html", b"<pre", b"<table", b"<body")
HTML_EXTENSIONS = (".htm", ".html")
SNIFF_BYTES = 2048
UNKNOWN_FORMAT_MESSAGE = "Not a Meet Manager file this app can read (expected a backup .zip, .mdb, PDF, HTML or text report)."
NOTHING_FOUND_MESSAGE = "No events were found in this file. Is it a heat sheet, meet program or entry report?"


def detect_format(path: Path, original_name: str = "") -> str:
    """Which kind of meet file this is (one of the ``MEET_FILE_FORMAT_*`` constants)."""
    name = (original_name or path.name).lower()
    with path.open("rb") as handle:
        head = handle.read(SNIFF_BYTES)
    if head.startswith(PDF_SIGNATURE):
        return constants.MEET_FILE_FORMAT_PDF
    if head[ACCESS_SIGNATURE_OFFSET:].startswith(ACCESS_SIGNATURE) or name.endswith(DATABASE_EXTENSIONS):
        return constants.MEET_FILE_FORMAT_DATABASE
    if zipfile.is_zipfile(path):
        return constants.MEET_FILE_FORMAT_DATABASE
    lowered = head.lower()
    if name.endswith(HTML_EXTENSIONS) or any(marker in lowered for marker in HTML_MARKERS):
        return constants.MEET_FILE_FORMAT_HTML
    if b"\x00" in head:
        raise MeetFileError(UNKNOWN_FORMAT_MESSAGE)
    return constants.MEET_FILE_FORMAT_TEXT


_READERS = {
    constants.MEET_FILE_FORMAT_DATABASE: read_meet_manager_database,
    constants.MEET_FILE_FORMAT_PDF: read_pdf_report,
    constants.MEET_FILE_FORMAT_HTML: read_html_report,
    constants.MEET_FILE_FORMAT_TEXT: read_text_report,
}


def read_meet_file(path: Path, original_name: str = "") -> tuple[MeetProgram, str]:
    """Read a meet file.

    Args:
        path: The file on disk.
        original_name: The name it was uploaded with (a hint for the format).

    Returns:
        The meet program and the detected format.

    Raises:
        MeetFileError: If the file cannot be read or holds no events.
    """
    file_format = detect_format(path, original_name)
    program = _READERS[file_format](path)
    if not program.events:
        raise MeetFileError(NOTHING_FOUND_MESSAGE)
    return program, file_format
