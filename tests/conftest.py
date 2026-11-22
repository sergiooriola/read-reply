import pytest


@pytest.fixture(autouse=True)
def no_real_herdr(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keeps every test away from the Herdr session it runs in.

    A test that needs Herdr points HERDR_BIN_PATH to a fake one.
    """
    monkeypatch.setenv("HERDR_BIN_PATH", "/nonexistent/herdr")
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)
