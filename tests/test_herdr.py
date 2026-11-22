import json
import shlex
from pathlib import Path

import pytest

from read_reply.errors import UserError
from read_reply.herdr import Agent, agent_in, notify


def fake_herdr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, output: str, code: int
) -> None:
    """A herdr executable that prints `output` and exits with `code`."""
    script = tmp_path / "herdr"
    script.write_text(f"#!/bin/sh\ncat <<'EOF'\n{output}\nEOF\nexit {code}\n")
    script.chmod(0o755)
    monkeypatch.setenv("HERDR_BIN_PATH", str(script))


def test_agent_in_returns_the_kind_and_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = {"agent": "claude", "kind": "id", "value": "abc-123"}
    response = {"result": {"agent": {"agent": "claude", "agent_session": session}}}
    fake_herdr(tmp_path, monkeypatch, json.dumps(response), 0)

    assert agent_in("w1:p1") == Agent(kind="claude", session="abc-123")


def test_agent_in_explains_a_pane_without_an_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = {
        "error": {"code": "agent_not_found", "message": "agent target w1:p2 not found"}
    }
    fake_herdr(tmp_path, monkeypatch, json.dumps(error), 1)

    with pytest.raises(UserError, match="no tiene ningún agente"):
        agent_in("w1:p2")


def test_agent_in_explains_an_agent_without_a_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    response = {"result": {"agent": {"agent": "codex", "agent_session": None}}}
    fake_herdr(tmp_path, monkeypatch, json.dumps(response), 0)

    with pytest.raises(UserError, match="qué conversación tiene"):
        agent_in("w1:p1")


def test_notify_shows_a_herdr_notification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = tmp_path / "calls"
    script = tmp_path / "herdr"
    script.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > {shlex.quote(str(calls))}\n')
    script.chmod(0o755)
    monkeypatch.setenv("HERDR_BIN_PATH", str(script))

    notify("Leer respuesta", "Sin agente.")

    assert calls.read_text().splitlines() == [
        "notification",
        "show",
        "Leer respuesta",
        "--body",
        "Sin agente.",
    ]


def test_notify_without_herdr_does_nothing() -> None:
    notify("Leer respuesta", "Sin agente.")
