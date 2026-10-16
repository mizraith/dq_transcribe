"""Guard: nothing from an official's membership card is ever committed.

The owner's rule (2026-10-16): camera frames and diagnostics from the tablet stay on
the tablet (``~/.officials_signin/diagnostics``) and are never pushed to a repo. This
test fails if a tracked file is a camera picture or test video, or if any tracked text
shows a member ID that was not redacted (device task reports print ``Member Id: [ID]``).

Run from the repo root with:
    PYTHONPATH=src:tests python3 -m unittest discover -s tests/officials_signin
"""

from __future__ import annotations

import re
import shutil
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PICTURE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".bmp", ".gif", ".y4m", ".mp4", ".mov"}
# Pictures that are allowed: blank DQ slip forms (dq_transcribe's reference material).
ALLOWED_PICTURE_FOLDERS = ("reference/dq_slips/",)
# "Member Id: <10+ letters/digits>" is a real ID; "[ID]" or "(redacted)" is fine.
MEMBER_ID_PATTERN = re.compile(r"member\s*i[dl]\s*[:;]?\s*[A-Z0-9]{10,}", re.IGNORECASE)
TEXT_SUFFIXES = {".py", ".js", ".html", ".css", ".md", ".txt", ".sh", ".json", ".jsonl", ".toml", ".cfg", ".ini", ""}


def tracked_files() -> list[str]:
    """Files git tracks in this repo."""
    output = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files"], check=True, capture_output=True, text=True
    ).stdout
    return [line for line in output.splitlines() if line]


@unittest.skipUnless(shutil.which("git") and (REPO_ROOT / ".git").exists(), "needs a git checkout")
class NoCardDataInRepoTests(unittest.TestCase):
    """No card pictures or member IDs in tracked files."""

    def test_no_camera_pictures(self) -> None:
        pictures = [
            path for path in tracked_files()
            if Path(path).suffix.lower() in PICTURE_SUFFIXES and not path.startswith(ALLOWED_PICTURE_FOLDERS)
        ]
        self.assertEqual(pictures, [], "camera pictures must stay on the tablet")

    def test_no_unredacted_member_ids(self) -> None:
        leaks = []
        for path in tracked_files():
            if Path(path).suffix.lower() not in TEXT_SUFFIXES or "vendor/" in path:
                continue
            try:
                text = (REPO_ROOT / path).read_text(encoding="utf-8")
            except (UnicodeDecodeError, FileNotFoundError):
                continue
            if MEMBER_ID_PATTERN.search(text):
                leaks.append(path)
        self.assertEqual(leaks, [], "member IDs must be redacted")


if __name__ == "__main__":
    unittest.main()
