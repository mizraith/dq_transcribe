"""Tests for the self-restart check in officials_signin.__main__.

Run from the repo root with:
    PYTHONPATH=src:tests python3 -m unittest discover -s tests/officials_signin
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from officials_signin.__main__ import code_compiles, source_fingerprint

GOOD_SOURCE = "VALUE = 1\n"
BROKEN_SOURCE = "VALUE = (\n"


class ReloadCheckTests(unittest.TestCase):
    """The server restarts only for changed code that compiles."""

    def setUp(self) -> None:
        self.directory = Path(tempfile.mkdtemp())
        self.module = self.directory / "module.py"
        self.module.write_text(GOOD_SOURCE)

    def test_fingerprint_changes_when_a_file_changes(self) -> None:
        before = source_fingerprint(self.directory)
        stat = self.module.stat()
        os.utime(self.module, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
        self.assertNotEqual(source_fingerprint(self.directory), before)

    def test_fingerprint_changes_when_a_file_is_added(self) -> None:
        before = source_fingerprint(self.directory)
        (self.directory / "added.py").write_text(GOOD_SOURCE)
        self.assertNotEqual(source_fingerprint(self.directory), before)

    def test_broken_code_is_not_restarted_into(self) -> None:
        self.assertTrue(code_compiles(self.directory))
        self.module.write_text(BROKEN_SOURCE)
        with self.assertLogs(level="WARNING"):
            self.assertFalse(code_compiles(self.directory))


if __name__ == "__main__":
    unittest.main()
