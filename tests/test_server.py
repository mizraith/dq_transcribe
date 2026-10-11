"""Tests for dq_transcribe.server.

Run from the repo root with:
    PYTHONPATH=src python -m unittest discover -s tests
"""

from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path

from dq_transcribe import constants
from dq_transcribe.server import DqTranscribeServer, build_recording_path

LOOPBACK_HOST = "127.0.0.1"
EXAMPLE_AUDIO_BYTES = b"fake audio bytes"
EXAMPLE_WEBM_CONTENT_TYPE = "audio/webm;codecs=opus"
EXAMPLE_TIMESTAMP = datetime(2026, 10, 10, 19, 5, 0)


class BuildRecordingPathTests(unittest.TestCase):
    """build_recording_path chooses extensions from the media type."""

    def test_known_media_type_ignores_codec_parameters(self) -> None:
        path = build_recording_path(EXAMPLE_WEBM_CONTENT_TYPE, Path("recordings"), EXAMPLE_TIMESTAMP)
        self.assertEqual(path.suffix, constants.AUDIO_EXTENSION_BY_MEDIA_TYPE["audio/webm"])
        self.assertEqual(path.parent, Path("recordings"))

    def test_unknown_media_type_gets_fallback_extension(self) -> None:
        path = build_recording_path("application/x-weird", Path("recordings"), EXAMPLE_TIMESTAMP)
        self.assertEqual(path.suffix, constants.UNKNOWN_AUDIO_EXTENSION)


class ServerTests(unittest.TestCase):
    """End-to-end tests against a real server on an OS-chosen port."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.recordings_directory = Path(self.temporary_directory.name)
        self.server = DqTranscribeServer((LOOPBACK_HOST, 0), self.recordings_directory)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temporary_directory.cleanup()

    def _request(self, method: str, path: str, body: bytes | None = None, content_type: str = "") -> http.client.HTTPResponse:
        connection = http.client.HTTPConnection(LOOPBACK_HOST, self.port, timeout=5)
        headers = {constants.CONTENT_TYPE_HEADER: content_type} if content_type else {}
        connection.request(method, path, body=body, headers=headers)
        return connection.getresponse()

    def test_home_page_has_filled_in_placeholders(self) -> None:
        response = self._request("GET", constants.ROUTE_HOME)
        page = response.read().decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn(constants.ROUTE_UPLOAD_RECORDING, page)
        self.assertNotIn("${", page)

    def test_upload_saves_file_and_reports_size(self) -> None:
        response = self._request(
            "POST", constants.ROUTE_UPLOAD_RECORDING, EXAMPLE_AUDIO_BYTES, EXAMPLE_WEBM_CONTENT_TYPE
        )
        result = json.loads(response.read())
        self.assertEqual(response.status, 200)
        self.assertEqual(result[constants.RESPONSE_KEY_SIZE_BYTES], len(EXAMPLE_AUDIO_BYTES))
        saved_file = self.recordings_directory / result[constants.RESPONSE_KEY_SAVED_AS]
        self.assertEqual(saved_file.read_bytes(), EXAMPLE_AUDIO_BYTES)

    def test_empty_upload_is_rejected(self) -> None:
        response = self._request("POST", constants.ROUTE_UPLOAD_RECORDING, b"", EXAMPLE_WEBM_CONTENT_TYPE)
        self.assertEqual(response.status, 400)

    def test_unknown_route_is_404(self) -> None:
        self.assertEqual(self._request("GET", "/nope").status, 404)
        self.assertEqual(self._request("POST", "/nope", b"x").status, 404)


if __name__ == "__main__":
    unittest.main()
