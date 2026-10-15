"""Stand-in for whisper.cpp's whisper-server, for tests.

Accepts the same --host/--port flags (others ignored). POST /inference answers
with JSON whose text reports the request count and whether the multipart body
contained the WAV file field.
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

REQUEST_COUNT = 0


class Handler(BaseHTTPRequestHandler):
    """Answers /inference requests."""

    def do_POST(self) -> None:  # noqa: N802
        global REQUEST_COUNT
        REQUEST_COUNT += 1
        body = self.rfile.read(int(self.headers["Content-Length"]))
        has_file = b'name="file"' in body and b"RIFF" in body
        payload = json.dumps({"text": f" [Music] reply {REQUEST_COUNT} file={has_file} "}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: object) -> None:
        pass


def main() -> None:
    arguments = sys.argv[1:]
    host = arguments[arguments.index("--host") + 1]
    port = int(arguments[arguments.index("--port") + 1])
    HTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
