"""The desktop script's side in Python. desktop.ps1 itself runs only on
Windows: see the README."""

import json
import time
from pathlib import Path

import pytest

from read_reply import desktop
from read_reply.desktop import Desktop, Monitor, window_position


@pytest.mark.parametrize(
    ("monitor", "position"),
    [
        (Monitor(left=0, top=0, right=1920, bottom=1080, scale=1.0), (1608, 958)),
        # 2560 x 1600 at 150 %, to the right of the first one
        (Monitor(left=1920, top=0, right=4480, bottom=1600, scale=1.5), (3315, 945)),
    ],
    ids=["100%", "150%"],
)
def test_the_window_goes_to_the_bottom_right_corner(
    monitor: Monitor, position: tuple[int, int]
) -> None:
    assert window_position(monitor) == position


def fake_powershell(monkeypatch: pytest.MonkeyPatch, script: Path, body: str) -> None:
    script.write_text("#!/bin/sh\n" + body)
    script.chmod(0o755)
    monkeypatch.setattr(desktop, "POWERSHELL", str(script))


MONITOR = {"left": 0, "top": 0, "right": 1920, "bottom": 1080, "scale": 1.5}


def test_the_script_tells_the_monitor_and_hears_when_edge_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    received = tmp_path / "received"
    answer = f"echo '{json.dumps(MONITOR)}'\n"
    fake_powershell(
        monkeypatch, tmp_path / "ps", answer + f'read line\necho "$line" > {received}\n'
    )

    with Desktop() as script:
        monitor = script.monitor()
        script.give_focus_back()

    assert monitor == Monitor(**MONITOR)  # type: ignore[arg-type]
    assert received.read_text() == "edge started\n"


def test_without_powershell_the_reading_goes_on() -> None:
    with Desktop() as script:
        assert script.monitor() is None
        script.give_focus_back()


def test_an_answer_that_is_not_a_monitor_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_powershell(monkeypatch, tmp_path / "ps", "echo 'Add-Type: error'\n")

    with Desktop() as script:
        assert script.monitor() is None


def test_a_script_that_hangs_is_waited_for_briefly_then_ended(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_powershell(monkeypatch, tmp_path / "ps", "trap '' TERM\nexec sleep 30\n")
    monkeypatch.setattr(desktop, "MONITOR_TIMEOUT_S", 0.2)
    start = time.monotonic()

    with Desktop() as script:
        assert script.monitor() is None

    assert time.monotonic() - start < 5
