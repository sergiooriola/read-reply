import fcntl
from pathlib import Path

import pytest

from read_reply import cli, herdr
from read_reply.errors import UserError
from read_reply.player import Player, request_stop


def test_print_writes_the_chunks_without_speaking(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "reply_chunks", lambda pane: [f"Panel {pane}.", "Fin."])

    cli.main(["--pane", "w1:p1", "--print"])

    assert capsys.readouterr().out == "Panel w1:p1.\n\nFin.\n"


def test_the_pane_comes_from_herdr(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HERDR_ACTIVE_PANE_ID", "w2:p3")
    monkeypatch.setattr(cli, "reply_chunks", lambda pane: [pane])

    cli.main(["--print"])

    assert capsys.readouterr().out == "w2:p3\n"


def test_without_a_pane_it_explains_and_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HERDR_ACTIVE_PANE_ID", raising=False)

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--print"])

    assert exit_info.value.code == 2


def test_errors_are_reported_and_exit_with_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail(pane: str) -> list[str]:
        raise UserError("El panel activo no tiene ningún agente.")

    notifications: list[tuple[str, str]] = []
    monkeypatch.setattr(cli, "reply_chunks", fail)
    monkeypatch.setattr(
        herdr, "notify", lambda title, body: notifications.append((title, body))
    )

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--pane", "w1:p1", "--print"])

    assert exit_info.value.code == 1
    assert "no tiene ningún agente" in capsys.readouterr().err
    assert notifications == [
        ("Leer respuesta", "El panel activo no tiene ningún agente.")
    ]


def test_a_press_during_a_reading_stops_it(tmp_path: Path) -> None:
    with (tmp_path / "lock").open("w") as lock, Player(tmp_path) as reading:
        fcntl.flock(lock, fcntl.LOCK_EX)

        cli.read_or_stop("w1:p1", tmp_path)

        assert reading.stop_requested


def test_a_stop_during_the_preparation_skips_speaking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def prepare_and_get_stopped(pane: str) -> list[str]:
        request_stop(tmp_path)
        return ["Hola."]

    def must_not_play(self: Player, chunks: list[str]) -> None:
        raise AssertionError("it spoke after a stop")

    monkeypatch.setattr(cli, "reply_chunks", prepare_and_get_stopped)
    monkeypatch.setattr(Player, "play", must_not_play)

    cli.read_or_stop("w1:p1", tmp_path)


def test_a_reply_with_nothing_to_say_is_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "agent_in", lambda pane: None)
    monkeypatch.setattr(cli, "last_reply", lambda agent: "---")

    with pytest.raises(UserError, match="no tiene texto que leer"):
        cli.reply_chunks("w1:p1")


def test_the_state_lives_in_the_runtime_dir_or_in_the_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    assert cli.state_dir() == tmp_path / "run" / "read-reply"

    monkeypatch.delenv("XDG_RUNTIME_DIR")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert cli.state_dir() == tmp_path / ".cache" / "read-reply"
