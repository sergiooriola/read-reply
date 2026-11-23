import pytest


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

    A test that needs PowerShell points desktop.POWERSHELL to a fake one.
    """
    monkeypatch.setattr("read_reply.desktop.POWERSHELL", "/nonexistent/powershell")
