"""Command-line entry point: ``python -m officials_signin`` starts the app.

Creates the database if needed and runs the local web server until it is
interrupted (Ctrl+C or SIGTERM). Open http://localhost:8010 in Chrome.

The server watches its own Python files. When they change (the tablet pulls new
code from GitHub automatically) and the new code compiles, it restarts itself in
place (same process ID, a second or two), so the page and the server always run
the same version. Web page files need no restart: they are read on every request.
"""

from __future__ import annotations

import logging
import os
import py_compile
import signal
import sys
import threading
from pathlib import Path

from officials_signin import constants
from officials_signin.database import Database
from officials_signin.server import SigninServer

LOGGER = logging.getLogger(__name__)
_PACKAGE_DIRECTORY = Path(__file__).parent
_PYTHON_FILE_PATTERN = "*.py"


def _exit_on_terminate(signal_number: int, frame: object) -> None:
    """Turn SIGTERM (for example from pkill) into a normal shutdown."""
    raise KeyboardInterrupt


def source_fingerprint(directory: Path = _PACKAGE_DIRECTORY) -> tuple[tuple[str, int], ...]:
    """Names and modification times of the package's Python files.

    Args:
        directory: Package folder to watch.

    Returns:
        A value that changes whenever a Python file is added, removed or edited.
    """
    return tuple(sorted((path.name, path.stat().st_mtime_ns) for path in directory.glob(_PYTHON_FILE_PATTERN)))


def code_compiles(directory: Path = _PACKAGE_DIRECTORY) -> bool:
    """True when every Python file in the package compiles (safe to restart into)."""
    try:
        for path in directory.glob(_PYTHON_FILE_PATTERN):
            py_compile.compile(str(path), doraise=True)
    except py_compile.PyCompileError as error:
        LOGGER.warning("New code does not compile; keeping the running version: %s", error.msg)
        return False
    return True


def watch_for_code_changes(web_server: SigninServer, restart_requested: threading.Event) -> None:
    """Ask the server to stop (so ``main`` can restart it) when the code changes.

    Runs forever in a daemon thread. A change must look the same on two checks
    in a row (a pull may still be writing files) and must compile.
    """
    running = source_fingerprint()
    previous = running
    rejected = None  # a change that did not compile (reported once, not every check)
    while not restart_requested.wait(constants.CODE_RELOAD_CHECK_SECONDS):
        current = source_fingerprint()
        if current != running and current == previous and current != rejected:
            if not code_compiles():
                rejected = current
                continue
            LOGGER.info("Code changed on disk; restarting the sign-in server")
            restart_requested.set()
            web_server.shutdown()
            return
        previous = current


def main() -> None:
    """Start the app and run until interrupted (restarting itself after code updates)."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    signal.signal(signal.SIGTERM, _exit_on_terminate)
    database = Database(constants.DATABASE_PATH)
    database.initialize()
    web_server = SigninServer((constants.SERVER_HOST, constants.SERVER_PORT), database)
    restart_requested = threading.Event()
    threading.Thread(
        target=watch_for_code_changes, args=(web_server, restart_requested), daemon=True
    ).start()
    address = f"http://{constants.SERVER_DISPLAY_HOST}:{constants.SERVER_PORT}{constants.ROUTE_HOME}"
    print(f"{constants.APP_TITLE} running. Open {address} in Chrome. Press Ctrl+C to stop.", flush=True)
    try:
        web_server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        web_server.server_close()
    if restart_requested.is_set():
        # Replace this process with a fresh one running the new code (same PID and environment).
        os.execv(sys.executable, [sys.executable, "-m", constants.APP_NAME])


if __name__ == "__main__":
    main()
