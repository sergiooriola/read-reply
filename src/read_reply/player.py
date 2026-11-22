"""Speaks text through headless Microsoft Edge.

Edge's implementation of the standard Web Speech API includes Microsoft's
natural online voices. A throwaway HTTP server on 127.0.0.1, which WSL
forwards to Windows, hands the page (player.html) the text and any stop
request. The page closes itself when it ends, and headless Edge exits with it.
"""

import base64
import re
import secrets
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from json import dumps
from pathlib import Path
from types import TracebackType
from typing import Any, Self
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from read_reply.errors import UserError

EDGE = Path("/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")
# The first voice that Edge offers wins.
# Álvaro needs internet; Pablo comes with Windows.
VOICES = (
    "Microsoft Álvaro Online (Natural) - Spanish (Spain)",
    "Microsoft Pablo - Spanish (Spain)",
)
RATE = 1.0
EDGE_START_TIMEOUT_S = 20
STOP_GRACE_S = 3
STOP_URL_FILE = "stop-url"


class Player:
    """One reading: the page's server, and Edge while it speaks.

    The server starts on entering the context, before the text is ready, so
    that a second key press can already stop the reading.
    """

    def __init__(self, state_dir: Path) -> None:
        self._stop_url_file = state_dir / STOP_URL_FILE
        self._page = files("read_reply").joinpath("player.html").read_bytes()
        self._chunks: list[str] = []
        self._page_loaded = threading.Event()
        self._stop_requested = threading.Event()
        self._finished = threading.Event()
        self._errors: list[str] = []
        token = secrets.token_urlsafe(16)
        self._server = ThreadingHTTPServer(
            ("127.0.0.1", 0), self._handler(f"/{token}/")
        )
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}/{token}/"

    def __enter__(self) -> Self:
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        self._stop_url_file.write_text(self.url + "stop")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._stop_url_file.unlink(missing_ok=True)
        self._server.shutdown()
        self._server.server_close()

    @property
    def stop_requested(self) -> bool:
        return self._stop_requested.is_set()

    def play(self, chunks: list[str]) -> None:
        """Speaks the chunks, and returns when they end or a stop arrives."""
        if not EDGE.exists():
            raise UserError(f"No encuentro Microsoft Edge en {EDGE}.")
        self._chunks = chunks
        profile = edge_profile()
        edge = subprocess.Popen(
            [
                str(EDGE),
                "--headless",
                f"--user-data-dir={profile}",
                # The page speaks without a click, which Chromium otherwise requires.
                "--autoplay-policy=no-user-gesture-required",
                "--no-first-run",
                "--disable-extensions",
                "--disable-sync",
                "--disable-component-update",
                self.url,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd="/mnt/c",  # Windows programs need a Windows working directory
        )
        try:
            if not self._page_loaded.wait(EDGE_START_TIMEOUT_S):
                raise UserError("Edge no ha arrancado a tiempo.")
            stop_deadline: float | None = None
            while not self._finished.wait(0.2) and edge.poll() is None:
                if self.stop_requested:
                    stop_deadline = stop_deadline or time.monotonic() + STOP_GRACE_S
                    if time.monotonic() > stop_deadline:
                        break  # the page did not react; Edge is closed below
            edge.wait(timeout=STOP_GRACE_S)
        except subprocess.TimeoutExpired:
            pass
        finally:
            if edge.poll() is None:
                stop_edge(profile)
                edge.kill()
        if self._errors:
            errors = ", ".join(sorted(set(self._errors)))
            raise UserError(f"Edge no ha podido leerla: {errors}.")

    def _handler(self, prefix: str) -> type[BaseHTTPRequestHandler]:
        """The request handler of the page's server, under a secret path."""
        player = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                match self._route():
                    case "":
                        self._reply(player._page, "text/html; charset=utf-8")
                        player._page_loaded.set()
                    case "reply":
                        reply = {
                            "chunks": player._chunks,
                            "voices": VOICES,
                            "rate": RATE,
                        }
                        self._reply(dumps(reply).encode(), "application/json")
                    case "state":
                        state = {"stop": player.stop_requested}
                        self._reply(dumps(state).encode(), "application/json")
                    case _:
                        self.send_error(404)

            def do_POST(self) -> None:
                match self._route():
                    case "stop":
                        player._stop_requested.set()
                    case "error":
                        length = int(self.headers["Content-Length"] or 0)
                        player._errors.append(self.rfile.read(length).decode())
                    case "finished":
                        player._finished.set()
                    case _:
                        self.send_error(404)
                        return
                self.send_response(204)
                self.end_headers()

            def _route(self) -> str | None:
                path = urlsplit(self.path).path
                return path.removeprefix(prefix) if path.startswith(prefix) else None

            def _reply(self, body: bytes, content_type: str) -> None:
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: Any) -> None:
                pass  # no log line per request

        return Handler


def request_stop(state_dir: Path) -> None:
    """Asks the reading in progress, if any, to stop."""
    try:
        url = (state_dir / STOP_URL_FILE).read_text()
        urlopen(Request(url, method="POST"), timeout=2).close()
    except OSError:
        pass  # it is starting or ending; another press will do


def edge_profile() -> str:
    """A dedicated Edge profile in %LOCALAPPDATA%, apart from the person's own."""
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", "echo %LOCALAPPDATA%"],
        capture_output=True,
        text=True,
        cwd="/mnt/c",
        check=False,
    )
    local_app_data = result.stdout.strip()
    if not re.match(r"^[A-Za-z]:\\", local_app_data):
        raise UserError("No encuentro la carpeta de datos de Windows (%LOCALAPPDATA%).")
    return local_app_data + r"\read-reply\edge-profile"


def stop_edge(profile: str) -> None:
    """Ends the Edge processes that use the profile, for a page that hung."""
    quoted = profile.replace("'", "''")
    script = (
        "Get-CimInstance Win32_Process -Filter \"Name = 'msedge.exe'\" | "
        f"Where-Object {{ $_.CommandLine -and $_.CommandLine.Contains('{quoted}') }} | "
        "ForEach-Object { "
        "Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode()
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True,
        cwd="/mnt/c",
        check=False,
    )
