"""The desktop script's side in Python. desktop.ps1 itself runs only on
Windows: see the README."""

import json
import time
from pathlib import Path

import pytest

from read_reply import desktop
from read_reply.desktop import Desktop, Terminal, window_pixels, window_position


@pytest.mark.parametrize(
    ("terminal", "position"),
    [
        (Terminal(100, 50, 1700, monitor_left=0, monitor_top=0, scale=1.0), (730, 58)),
        # On a monitor at 150 %, to the right of one at 100 % that is 1920 wide:
        # its pixels from its corner count two thirds.
        (
            Terminal(2020, 100, 4420, monitor_left=1920, monitor_top=0, scale=1.5),
            (2617, 75),
        ),
    ],
    ids=["100%", "150%"],
)
def test_the_window_goes_to_the_top_of_the_terminal_centred(
    terminal: Terminal, position: tuple[int, int]
) -> None:
    assert window_position(terminal) == position


def test_the_script_puts_the_window_in_physical_pixels() -> None:
    terminal = Terminal(2020, 100, 4420, monitor_left=1920, monitor_top=0, scale=1.5)

    # 340 x 110 at 150 % is 510 pixels wide; 8 of margin, 12.
    assert window_pixels(terminal) == (2965, 112)


def fake_powershell(monkeypatch: pytest.MonkeyPatch, script: Path, body: str) -> None:
    script.write_text("#!/bin/sh\n" + body)
    script.chmod(0o755)
    monkeypatch.setattr(desktop, "POWERSHELL", str(script))
    monkeypatch.setattr(desktop, "WINDOWS_CWD", str(script.parent))  # not on WSL


TERMINAL = {
    "left": 0,
    "top": 0,
    "right": 1920,
    "monitor_left": 0,
    "monitor_top": 0,
    "scale": 1.5,
}


def test_the_script_tells_the_terminal_and_hears_when_edge_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    received = tmp_path / "received"
    answer = f"echo '{json.dumps(TERMINAL)}'\n"
    fake_powershell(
        monkeypatch,
        tmp_path / "ps",
        answer + f'read -r line\nprintf "%s\\n" "$line" > {received}\n',
    )

    with Desktop() as script:
        terminal = script.terminal()
        script.edge_started("C:\\profile")

    assert terminal == Terminal(**TERMINAL)  # type: ignore[arg-type]
    edge = json.loads(received.read_text())
    assert edge == {"profile": "C:\\profile", "x": 705, "y": 12}


def test_without_powershell_the_reading_goes_on() -> None:
    with Desktop() as script:
        assert script.terminal() is None
        script.edge_started("C:\\profile")


@pytest.mark.parametrize(
    "answer",
    [
        "Add-Type: error",
        "null",
        json.dumps(TERMINAL | {"right": 0}),
        json.dumps(TERMINAL | {"scale": 0}),
    ],
    ids=["error", "no-terminal", "no-frame", "no-scale"],
)
def test_an_answer_that_is_not_a_terminal_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, answer: str
) -> None:
    fake_powershell(monkeypatch, tmp_path / "ps", f"echo '{answer}'\n")

    with Desktop() as script:
        assert script.terminal() is None


def test_no_terminal_is_an_answer_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    received = tmp_path / "received"
    fake_powershell(
        monkeypatch,
        tmp_path / "ps",
        f'echo null\nread -r line\nprintf "%s\\n" "$line" > {received}\n',
    )
    start = time.monotonic()

    with Desktop() as script:
        assert script.terminal() is None
        script.edge_started("C:\\profile")  # asks no more

    assert time.monotonic() - start < desktop.MONITOR_TIMEOUT_S
    assert json.loads(received.read_text()) == {"profile": "C:\\profile"}


def test_a_script_that_hangs_is_waited_for_briefly_then_ended(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_powershell(monkeypatch, tmp_path / "ps", "trap '' TERM\nexec sleep 30\n")
    monkeypatch.setattr(desktop, "MONITOR_TIMEOUT_S", 0.2)
    start = time.monotonic()

    with Desktop() as script:
        assert script.terminal() is None

    assert time.monotonic() - start < 5
