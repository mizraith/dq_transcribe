"""Local HTTP server for dq_transcribe.

Serves the web pages and accepts audio uploads recorded in the browser. It
uses only the Python standard library, so it installs nothing and runs the
same on Termux (Android) and Windows.

The server binds to the loopback address only: it is reachable from this
device and nowhere else on the network.
"""

from __future__ import annotations

import json
import logging
import string
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from dq_transcribe import constants

LOGGER = logging.getLogger(__name__)

_WEB_DIRECTORY = Path(__file__).parent / constants.WEB_DIRECTORY_NAME


def build_recording_path(
    content_type_header: str,
    recordings_directory: Path,
    timestamp: datetime | None = None,
) -> Path:
    """Choose a unique, server-generated path for an uploaded recording.

    The filename never comes from the client, which rules out path tricks.

    Args:
        content_type_header: Raw Content-Type header sent with the upload, for
            example ``"audio/webm;codecs=opus"``. Parameters after ``;`` are ignored.
        recordings_directory: Directory the recording will be saved in.
        timestamp: Time used in the filename. Defaults to now.

    Returns:
        Path inside ``recordings_directory`` with an extension matching the media type.
    """
    media_type = content_type_header.split(";")[0].strip().lower()
    extension = constants.AUDIO_EXTENSION_BY_MEDIA_TYPE.get(
        media_type, constants.UNKNOWN_AUDIO_EXTENSION
    )
    moment = timestamp or datetime.now()
    stamp = moment.strftime(constants.RECORDING_TIMESTAMP_FORMAT)
    return recordings_directory / f"{constants.RECORDING_FILENAME_PREFIX}_{stamp}{extension}"


def render_mic_test_page() -> bytes:
    """Render the microphone test page with shared constants filled in.

    Returns:
        The finished HTML document, UTF-8 encoded.
    """
    template = string.Template((_WEB_DIRECTORY / constants.MIC_TEST_PAGE_FILENAME).read_text("utf-8"))
    page = template.substitute(
        upload_endpoint=constants.ROUTE_UPLOAD_RECORDING,
        record_seconds=constants.MIC_TEST_RECORD_SECONDS,
        key_saved_as=constants.RESPONSE_KEY_SAVED_AS,
        key_size_bytes=constants.RESPONSE_KEY_SIZE_BYTES,
        key_error=constants.RESPONSE_KEY_ERROR,
    )
    return page.encode("utf-8")


class DqTranscribeServer(ThreadingHTTPServer):
    """HTTP server that knows where to store uploaded recordings.

    Attributes:
        recordings_directory: Directory where uploaded audio is saved.
    """

    def __init__(self, server_address: tuple[str, int], recordings_directory: Path) -> None:
        """Create the server and make sure the recordings directory exists.

        Args:
            server_address: ``(host, port)`` to bind. Use port 0 to let the OS choose.
            recordings_directory: Directory where uploaded audio is saved.
        """
        self.recordings_directory = recordings_directory
        self.recordings_directory.mkdir(parents=True, exist_ok=True)
        super().__init__(server_address, RequestHandler)


class RequestHandler(BaseHTTPRequestHandler):
    """Handles page requests and recording uploads."""

    server: DqTranscribeServer

    def do_GET(self) -> None:  # noqa: N802 (name required by BaseHTTPRequestHandler)
        """Serve the microphone test page at the home route."""
        if self.path == constants.ROUTE_HOME:
            self._send_bytes(HTTPStatus.OK, constants.HTML_CONTENT_TYPE, render_mic_test_page())
        else:
            self._send_json_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:  # noqa: N802 (name required by BaseHTTPRequestHandler)
        """Save an uploaded recording and report what was stored."""
        if self.path != constants.ROUTE_UPLOAD_RECORDING:
            self._send_json_error(HTTPStatus.NOT_FOUND, "Not found")
            return

        try:
            body_length = int(self.headers.get(constants.CONTENT_LENGTH_HEADER, ""))
        except ValueError:
            self._send_json_error(HTTPStatus.LENGTH_REQUIRED, "Content-Length header required")
            return
        if body_length <= 0:
            self._send_json_error(HTTPStatus.BAD_REQUEST, "Empty upload")
            return
        if body_length > constants.MAX_UPLOAD_BYTES:
            self._send_json_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Upload too large")
            return

        audio_bytes = self.rfile.read(body_length)
        recording_path = build_recording_path(
            self.headers.get(constants.CONTENT_TYPE_HEADER, ""),
            self.server.recordings_directory,
        )
        recording_path.write_bytes(audio_bytes)
        LOGGER.info("Saved %s (%d bytes)", recording_path.name, len(audio_bytes))
        self._send_json(
            HTTPStatus.OK,
            {
                constants.RESPONSE_KEY_SAVED_AS: recording_path.name,
                constants.RESPONSE_KEY_SIZE_BYTES: len(audio_bytes),
            },
        )

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        """Route request logging through the logging module instead of stderr."""
        LOGGER.info("%s - %s", self.address_string(), format % args)

    def _send_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
        """Send a JSON response."""
        self._send_bytes(status, constants.JSON_CONTENT_TYPE, json.dumps(payload).encode("utf-8"))

    def _send_json_error(self, status: HTTPStatus, message: str) -> None:
        """Send a JSON error response with a human-readable message."""
        self._send_json(status, {constants.RESPONSE_KEY_ERROR: message})

    def _send_bytes(self, status: HTTPStatus, content_type: str, body: bytes) -> None:
        """Send a complete response with the given status, content type, and body."""
        self.send_response(status)
        self.send_header(constants.CONTENT_TYPE_HEADER, content_type)
        self.send_header(constants.CONTENT_LENGTH_HEADER, str(len(body)))
        self.end_headers()
        self.wfile.write(body)
