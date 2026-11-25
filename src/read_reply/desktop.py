"""The reading window's place on the Windows desktop, and the focus handed back.

The window opens at the top of the terminal, centred, and stays above it; the
focus goes back to the window that had it: listening must not take the
keyboard away. Only Windows knows its windows, so a PowerShell script
(desktop.ps1) does both.
"""

import json
import select
import subprocess
from contextlib import suppress
from dataclasses import dataclass
from importlib.resources import files
from types import TracebackType
from typing import Self

from read_reply import windows

# The window's size, in CSS pixels: player.html is laid out for it.
WINDOW_SIZE = (340, 140)
MARGIN = 8
MONITOR_TIMEOUT_S = 3.0


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
    """Top centre of the terminal, near enough, for Edge's --window-position.

    Chromium places windows in device-independent pixels. Taking that each
    monitor keeps its top-left corner, and that distances within it are
    divided by its scale, holds for the main monitor and those right of or
    below one at 100 %; elsewhere the window still opens on the terminal's
    monitor, where window_pixels() then puts it exactly.
    """

    def independent(pixel: float, origin: int) -> float:
        return origin + (pixel - origin) / terminal.scale

    width, _height = WINDOW_SIZE
    centre = independent((terminal.left + terminal.right) / 2, terminal.monitor_left)
    top = independent(terminal.top, terminal.monitor_top)
    return round(centre - width / 2), round(top + MARGIN)


def window_pixels(terminal: Terminal) -> tuple[int, int]:
    """Top centre of the terminal, in physical pixels, for desktop.ps1."""
    width, _height = WINDOW_SIZE
    centre = (terminal.left + terminal.right) / 2
    return (
        round(centre - width * terminal.scale / 2),
        round(terminal.top + MARGIN * terminal.scale),
    )


class Desktop:
    """desktop.ps1 for one reading. Without it, the window opens where Edge
    decides and keeps the focus, but the reading goes on."""

    def __init__(self) -> None:
        self._script: subprocess.Popen[str] | None = None
        self._terminal: Terminal | None = None
        self._asked = False  # the script answers once

    def __enter__(self) -> Self:
        script = files("read_reply").joinpath("desktop.ps1").read_text()
        with suppress(OSError):  # not on Windows
            self._script = subprocess.Popen(
                windows.powershell_command(script),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                cwd=windows.WINDOWS_CWD,
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
        if self._script.stdout:
            self._script.stdout.close()

    def terminal(self) -> Terminal | None:
        """The terminal's window when the reading started. Asks once."""
        if not self._asked:
            self._asked = True
            self._terminal = self._read_terminal()
        return self._terminal

    def _read_terminal(self) -> Terminal | None:
        if self._script is None or self._script.stdout is None:
            return None
        stdout = self._script.stdout
        ready, _, _ = select.select([stdout], [], [], MONITOR_TIMEOUT_S)
        if not ready:
            return None
        try:
            fields = json.loads(stdout.readline())
            terminal = Terminal(
                left=int(fields["left"]),
                top=int(fields["top"]),
                right=int(fields["right"]),
                monitor_left=int(fields["monitor_left"]),
                monitor_top=int(fields["monitor_top"]),
                scale=float(fields["scale"]),
            )
        except ValueError, KeyError, TypeError:  # TypeError: null, no terminal
            return None
        usable = terminal.right > terminal.left and terminal.scale > 0
        return terminal if usable else None

    def edge_started(self, profile: str) -> None:
        """Once Edge has started with that profile: the script puts its window
        in place and gives the focus back."""
        if self._script is None or self._script.stdin is None:
            return
        edge: dict[str, str | int] = {"profile": profile}
        if terminal := self.terminal():
            edge["x"], edge["y"] = window_pixels(terminal)
        with suppress(OSError):  # the script failed
            self._script.stdin.write(json.dumps(edge) + "\n")
            self._script.stdin.flush()
