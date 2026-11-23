"""The reading window's place on the Windows desktop, and the focus handed back.

The window opens at the top of the terminal, centred, and stays above it; the
focus goes back to the window that had it: listening must not take the
keyboard away. Only Windows knows its windows, so a PowerShell script
(desktop.ps1) does both.
"""

import base64
import json
import select
import subprocess
from contextlib import suppress
from dataclasses import dataclass
from importlib.resources import files
from types import TracebackType
from typing import Self

POWERSHELL = "powershell.exe"
# The window's size, in CSS pixels: player.html is laid out for it.
WINDOW_SIZE = (300, 110)
MARGIN = 8
MONITOR_TIMEOUT_S = 3.0


def powershell_command(script: str) -> list[str]:
    """The command that runs the script, passed whole: no quoting, no files."""
    encoded = base64.b64encode(script.encode("utf-16-le")).decode()
    return [POWERSHELL, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded]


@dataclass(frozen=True)
class Terminal:
    """The terminal window's frame and its monitor's top-left corner, in
    physical pixels, and the monitor's scale."""

    left: int
    top: int
    right: int
    monitor_left: int
    monitor_top: int
    scale: float


def window_position(terminal: Terminal) -> tuple[int, int]:
    """Top centre of the terminal, in the coordinates of Edge's --window-position.

    Chromium places windows in device-independent pixels: each monitor keeps
    its top-left corner, and distances within it are divided by its scale.
    """

    def independent(pixel: float, origin: int) -> float:
        return origin + (pixel - origin) / terminal.scale

    width, _height = WINDOW_SIZE
    centre = independent((terminal.left + terminal.right) / 2, terminal.monitor_left)
    top = independent(terminal.top, terminal.monitor_top)
    return round(centre - width / 2), round(top + MARGIN)


class Desktop:
    """desktop.ps1 for one reading. Without it, the window opens where Edge
    decides and keeps the focus, but the reading goes on."""

    def __init__(self) -> None:
        self._script: subprocess.Popen[str] | None = None

    def __enter__(self) -> Self:
        script = files("read_reply").joinpath("desktop.ps1").read_text()
        with suppress(OSError):  # not on Windows
            self._script = subprocess.Popen(
                powershell_command(script),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                cwd="/mnt/c",  # Windows programs need a Windows working directory
            )
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._script is None:
            return
        if self._script.stdin:
            with suppress(OSError):  # it ended already
                self._script.stdin.close()  # end of input: the script ends
        try:
            self._script.wait(timeout=1)
        except subprocess.TimeoutExpired:
            self._script.kill()
            self._script.wait()

    def terminal(self) -> Terminal | None:
        """The terminal's window when the reading started."""
        if self._script is None or self._script.stdout is None:
            return None
        stdout = self._script.stdout
        ready, _, _ = select.select([stdout], [], [], MONITOR_TIMEOUT_S)
        if not ready:
            return None
        try:
            fields = json.loads(stdout.readline())
            return Terminal(
                left=int(fields["left"]),
                top=int(fields["top"]),
                right=int(fields["right"]),
                monitor_left=int(fields["monitor_left"]),
                monitor_top=int(fields["monitor_top"]),
                scale=float(fields["scale"]) or 1.0,
            )
        except ValueError, KeyError, TypeError:
            return None

    def give_focus_back(self) -> None:
        """Call once Edge has started: its window will hand the focus back."""
        if self._script is None or self._script.stdin is None:
            return
        with suppress(OSError):  # the script failed
            self._script.stdin.write("edge started\n")
            self._script.stdin.flush()
