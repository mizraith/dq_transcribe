"""Read a Meet Manager report saved as PDF (heat sheet, meet program, psych sheet).

The text is taken out with ``pdftotext -layout`` (Termux: ``pkg install poppler``),
which keeps each printed line on one line, or with the ``pypdf`` package when
that is installed instead. The lines then go through the shared report parser.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from dq_transcribe import constants
from dq_transcribe.meet_files.errors import MeetFileError
from dq_transcribe.meet_files.model import MeetProgram
from dq_transcribe.meet_files.report_text import parse_report_text

NO_PDF_READER_MESSAGE = (
    "Can't read PDF files yet: install the PDF reader once (in Termux: pkg install poppler)."
)
LAYOUT_FLAG = "-layout"
STANDARD_OUTPUT = "-"


def pdf_text(path: Path) -> str:
    """The PDF's text, pages separated by form feeds, laid out as printed."""
    if shutil.which(constants.PDF_TO_TEXT_COMMAND):
        result = subprocess.run(
            [constants.PDF_TO_TEXT_COMMAND, LAYOUT_FLAG, str(path), STANDARD_OUTPUT],
            capture_output=True,
            text=True,
            timeout=constants.EXTERNAL_COMMAND_TIMEOUT_SECONDS,
            check=False,
        )
        if result.returncode != 0:
            raise MeetFileError(f"Could not read the PDF: {result.stderr.strip()[:200]}")
        return result.stdout
    try:
        import pypdf  # optional fallback
    except ImportError as error:
        raise MeetFileError(NO_PDF_READER_MESSAGE) from error
    reader = pypdf.PdfReader(str(path))
    return "\f".join(page.extract_text(extraction_mode="layout") or "" for page in reader.pages)


def read_pdf_report(path: Path) -> MeetProgram:
    """Read events, heats and entries from a PDF report."""
    return parse_report_text(pdf_text(path))
