from collections.abc import Callable
from pathlib import Path

import pytest

from read_reply import windows


@pytest.fixture(autouse=True)
def no_real_herdr(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keeps every test away from the Herdr session it runs in.

    A test that needs Herdr points HERDR_BIN_PATH to a fake one.
    """
    monkeypatch.setenv("HERDR_BIN_PATH", "/nonexistent/herdr")
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)


@pytest.fixture(autouse=True)
def no_real_desktop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keeps every test away from the Windows desktop it may run on.

    A test that needs PowerShell points windows.POWERSHELL to a fake one.
    """
    monkeypatch.setattr(windows, "POWERSHELL", "/nonexistent/powershell")


@pytest.fixture
def fake_powershell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Callable[[str], None]:
    """Puts a shell script with that body in PowerShell's place."""

    def install(body: str) -> None:
        script = tmp_path / "powershell"
        script.write_text("#!/bin/sh\n" + body)
        script.chmod(0o755)
        monkeypatch.setattr(windows, "POWERSHELL", str(script))
        monkeypatch.setattr(windows, "WINDOWS_CWD", str(tmp_path))  # not on WSL

    return install
