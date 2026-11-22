import fcntl
from pathlib import Path

import pytest

from read_reply import cli
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

    monkeypatch.setattr(cli, "reply_chunks", fail)

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--pane", "w1:p1", "--print"])

    assert exit_info.value.code == 1
    assert "no tiene ningún agente" in capsys.readouterr().err


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
