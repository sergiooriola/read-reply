"""Speaks text through Microsoft Edge, in a small window with its controls.

Edge's implementation of the standard Web Speech API includes Microsoft's
natural online voices. A throwaway HTTP server on 127.0.0.1, which WSL
forwards to Windows, hands the page (player.html and reading.mjs) the text and
any stop request. The page closes itself when it ends, and Edge exits with it.
"""

import re
import secrets
import subprocess
import threading
import time
from contextlib import ExitStack, suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from json import dumps
from pathlib import Path
from types import TracebackType
from typing import Any, Protocol, Self
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from read_reply.desktop import WINDOW_SIZE, Desktop, Terminal, window_position
from read_reply.errors import UserError
from read_reply.windows import WINDOWS_CWD, powershell_command

EDGE = Path("/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")
# The first voice that Edge offers wins. Álvaro needs internet; the page falls
# back to a local voice, such as Pablo, when an online one fails.
VOICES = (
    "Microsoft Álvaro Online (Natural) - Spanish (Spain)",
    "Microsoft Pablo - Spanish (Spain)",
)
EDGE_START_TIMEOUT_S = 20.0
STOP_GRACE_S = 3.0
POLL_INTERVAL_S = 0.2
STOP_URL_FILE = "stop-url"
# What the Web Speech API accepts; the page offers a narrower range.
RATE_MIN, RATE_MAX = 0.1, 10.0


class Process(Protocol):
    """The part of subprocess.Popen that waiting for Edge needs."""

    def poll(self) -> int | None: ...
    def wait(self, timeout: float | None = None) -> int: ...


class Player:
    """One reading: the page's server, and Edge while it speaks.

    The server and the desktop script start on entering the context, before
    the text is ready: a second key press can already stop the reading, and
    the window's place is known by the time Edge starts.
    """

    def __init__(self, state_dir: Path, rate_file: Path) -> None:
        self._stop_url_file = state_dir / STOP_URL_FILE
        self._rate_file = rate_file
        self._rate_lock = threading.Lock()  # one save at a time
        package = files("read_reply")
        self._files = {
            "": (package.joinpath("player.html").read_bytes(), "text/html"),
            "reading.mjs": (
                package.joinpath("reading.mjs").read_bytes(),
                "text/javascript",
            ),
        }
        self._desktop = Desktop()
        self._context = ExitStack()  # undoes __enter__
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
        # Whatever has started is undone if a later step fails.
        with ExitStack() as context:
            threading.Thread(target=self._server.serve_forever, daemon=True).start()
            context.callback(self._server.server_close)
            context.callback(self._server.shutdown)
            # Written whole, so that a second press never reads half of it.
            partial = self._stop_url_file.with_suffix(".partial")
            partial.write_text(self.url + "stop")
            partial.replace(self._stop_url_file)
            context.callback(self._stop_url_file.unlink, missing_ok=True)
            context.enter_context(self._desktop)
            self._context = context.pop_all()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._context.close()

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
            edge_command(self.url, profile, self._desktop.terminal()),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=WINDOWS_CWD,
        )
        self._desktop.edge_started(profile)
        try:
            self.wait_for(edge)
        finally:
            if edge.poll() is None:
                stop_edge(profile)
                edge.kill()
        if self._errors:
            errors = ", ".join(sorted(set(self._errors)))
            raise UserError(f"Edge no ha podido leerla: {errors}.")

    def wait_for(self, edge: Process) -> None:
        """Returns once the page has finished, or once a stop has had its time.

        Edge may still run on return after a stop; the caller closes it.
        """
        start_deadline = time.monotonic() + EDGE_START_TIMEOUT_S
        stop_deadline: float | None = None
        while not self._finished.wait(POLL_INTERVAL_S):
            edge_exited = edge.poll() is not None
            if self.stop_requested:
                if edge_exited or not self._page_loaded.is_set():
                    return  # nothing more will be heard
                stop_deadline = stop_deadline or time.monotonic() + STOP_GRACE_S
                if time.monotonic() > stop_deadline:
                    return  # the page did not react
            # "finished" may have arrived just after the wait above timed out.
            elif edge_exited and not self._finished.is_set():
                raise UserError("Edge se ha cerrado antes de terminar de leer.")
            elif not self._page_loaded.is_set() and time.monotonic() > start_deadline:
                raise UserError("Edge no ha arrancado a tiempo.")
        with suppress(subprocess.TimeoutExpired):
            edge.wait(timeout=STOP_GRACE_S)  # the page closed, so Edge is exiting

    def _handler(self, prefix: str) -> type[BaseHTTPRequestHandler]:
        """The request handler of the page's server, under a secret path."""
        player = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                match self._route():
                    case "" | "reading.mjs" as name:
                        body, content_type = player._files[name]
                        self._reply(body, content_type + "; charset=utf-8")
                        if name == "":
                            player._page_loaded.set()
                    case "reply":
                        reply = {
                            "chunks": player._chunks,
                            "voices": VOICES,
                            "rate": saved_rate(player._rate_file),
                        }
                        self._reply(dumps(reply).encode(), "application/json")
                    case "state":
                        state = {"stop": player.stop_requested}
                        self._reply(dumps(state).encode(), "application/json")
                    case _:
                        self.send_error(404)

            def do_POST(self) -> None:
                length = int(self.headers["Content-Length"] or 0)
                body = self.rfile.read(length).decode()
                match self._route():
                    case "stop":
                        player._stop_requested.set()
                    case "error":
                        player._errors.append(body)
                    case "rate":
                        with player._rate_lock:
                            saved = save_rate(player._rate_file, body)
                        if not saved:
                            self.send_error(400)
                            return
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


def saved_rate(path: Path) -> float:
    """The speed last chosen in the window, kept between readings.

    The page cannot keep it: its address has a new port each time, and the
    browser keeps data per address.
    """
    try:
        rate = float(path.read_text())
    except OSError, ValueError:
        return 1.0
    return rate if RATE_MIN <= rate <= RATE_MAX else 1.0


def save_rate(path: Path, text: str) -> bool:
    """Keeps the speed the page sends; False if it is not one."""
    try:
        rate = float(text)
    except ValueError:
        return False
    if not RATE_MIN <= rate <= RATE_MAX:  # NaN fails too
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".partial")
    partial.write_text(str(rate))
    partial.replace(path)
    return True


def edge_command(url: str, profile: str, terminal: Terminal | None) -> list[str]:
    """Edge with the page in a window of its own, in its own profile."""
    width, height = WINDOW_SIZE
    position = []
    if terminal:  # else where Edge decides
        x, y = window_position(terminal)
        position = [f"--window-position={x},{y}"]
    return [
        str(EDGE),
        f"--app={url}",  # a window with no tabs nor address bar
        f"--window-size={width},{height}",
        *position,
        f"--user-data-dir={profile}",
        # The page speaks without a click, which Chromium otherwise requires.
        "--autoplay-policy=no-user-gesture-required",
        "--no-first-run",
        "--disable-extensions",
        "--disable-sync",
        "--disable-component-update",
    ]


def request_stop(state_dir: Path, wait_s: float = 1.0) -> None:
    """Asks the reading in progress to stop.

    A reading that has just started publishes its stop address within
    milliseconds, so a missing address is looked for again for a moment.
    """
    deadline = time.monotonic() + wait_s
    while not (url := read_stop_url(state_dir)) and time.monotonic() < deadline:
        time.sleep(0.05)
    if not url:
        return  # no reading, or it is ending
    # Straight to 127.0.0.1: an http_proxy setting must not take the request away.
    opener = build_opener(ProxyHandler({}))
    with suppress(OSError):  # the reading ended meanwhile
        opener.open(Request(url, method="POST"), timeout=2).close()


def read_stop_url(state_dir: Path) -> str:
    try:
        return (state_dir / STOP_URL_FILE).read_text().strip()
    except FileNotFoundError:
        return ""


def edge_profile() -> str:
    """A dedicated Edge profile in %LOCALAPPDATA%, apart from the person's own."""
    # /u makes cmd.exe write UTF-16, whatever its code page, for paths with "é".
    result = subprocess.run(
        ["cmd.exe", "/d", "/u", "/c", "echo %LOCALAPPDATA%"],
        capture_output=True,
        cwd=WINDOWS_CWD,
        check=False,
    )
    local_app_data = result.stdout.decode("utf-16-le", errors="replace").strip()
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
    subprocess.run(
        powershell_command(script),
        capture_output=True,
        cwd=WINDOWS_CWD,
        check=False,
    )
