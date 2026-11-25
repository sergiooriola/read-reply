import fcntl
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from read_reply import cli, herdr
from read_reply.errors import UserError
from read_reply.herdr import Agent
from read_reply.player import Earlier, Player, request_stop


def agent_replies(
    monkeypatch: pytest.MonkeyPatch, *markdown: str, taken: list[str] | None = None
) -> None:
    """The agent in any pane is a Claude whose session is the pane, with these
    replies, newest first; taken, if given, records each one read."""

    def replies(agent: Agent) -> Iterator[str]:
        for reply in markdown:
            if taken is not None:
                taken.append(reply)
            yield reply.format(pane=agent.session)

    monkeypatch.setattr(cli, "agent_in", lambda pane: Agent("claude", pane))
    monkeypatch.setattr(cli, "replies", replies)


def test_print_writes_the_chunks_without_speaking(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    agent_replies(monkeypatch, "Panel {pane}.\n\nFin.", "Una anterior.")

    cli.main(["--pane", "w1:p1", "--print"])

    assert capsys.readouterr().out == "Panel w1:p1.\n\nFin.\n"


def test_the_pane_comes_from_herdr(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HERDR_ACTIVE_PANE_ID", "w2:p3")
    agent_replies(monkeypatch, "{pane}")

    cli.main(["--print"])

    assert capsys.readouterr().out == "w2:p3\n"


@pytest.mark.parametrize(
    ("args", "can_go_back"),
    [(["--pane", "w1:p1"], True), (["--clipboard"], False)],
    ids=["reply", "copied"],
)
def test_only_a_reply_can_go_back_to_earlier_ones(
    monkeypatch: pytest.MonkeyPatch, args: list[str], can_go_back: bool
) -> None:
    calls: list[Earlier | None] = []

    def read_or_stop(*args: Any) -> None:
        calls.append(args[3])

    monkeypatch.setattr(cli, "read_or_stop", read_or_stop)

    cli.main(args)

    assert (calls[0] is not None) is can_go_back


def test_without_a_pane_it_explains_and_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HERDR_ACTIVE_PANE_ID", raising=False)

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--print"])

    assert exit_info.value.code == 2


def test_the_copied_text_needs_no_pane(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("HERDR_ACTIVE_PANE_ID", raising=False)
    monkeypatch.setattr(cli, "clipboard_text", lambda: "● Uno.\n\n  - Dos")

    cli.main(["--clipboard", "--print"])

    assert capsys.readouterr().out == "Uno.\n\nDos\n"


@pytest.mark.parametrize("copied", ["", "\n  \n"], ids=["nothing", "blank"])
def test_nothing_copied_is_an_error(
    monkeypatch: pytest.MonkeyPatch, copied: str
) -> None:
    monkeypatch.setattr(cli, "clipboard_text", lambda: copied)

    with pytest.raises(UserError, match="No hay texto copiado"):
        cli.clipboard_chunks()


def test_errors_are_reported_and_exit_with_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail(pane: str) -> Agent:
        raise UserError("El panel activo no tiene ningún agente.")

    notifications: list[tuple[str, str]] = []
    monkeypatch.setattr(cli, "agent_in", fail)
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
    with (
        (tmp_path / "lock").open("w") as lock,
        Player(tmp_path, tmp_path / "rate") as reading,
    ):
        fcntl.flock(lock, fcntl.LOCK_EX)

        cli.read_or_stop(lambda: ["Hola."], tmp_path, tmp_path / "rate")

        assert reading.stop_requested


def test_a_stop_during_the_preparation_skips_speaking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def prepare_and_get_stopped() -> list[str]:
        request_stop(tmp_path)
        return ["Hola."]

    def must_not_play(
        self: Player, chunks: list[str], earlier: Earlier | None = None
    ) -> None:
        raise AssertionError("it spoke after a stop")

    monkeypatch.setattr(Player, "play", must_not_play)

    cli.read_or_stop(prepare_and_get_stopped, tmp_path, tmp_path / "rate")


@pytest.mark.parametrize(
    ("markdown", "message"),
    [
        ((), "todavía no ha terminado ninguna respuesta"),
        (("---", "Una anterior."), "no tiene texto que leer"),
    ],
    ids=["no reply", "nothing to say"],
)
def test_a_last_reply_that_cannot_be_read_is_an_error(
    monkeypatch: pytest.MonkeyPatch, markdown: tuple[str, ...], message: str
) -> None:
    agent_replies(monkeypatch, *markdown)

    with pytest.raises(UserError, match=message):
        cli.Replies("w1:p1").last()


def test_earlier_replies_are_read_only_as_far_as_asked_and_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    taken: list[str] = []
    agent_replies(monkeypatch, "Última.", "Penúltima.", "---", "Primera.", taken=taken)
    agent = cli.Replies("w1:p1")

    assert agent.last() == ["Última."]
    assert taken == ["Última."]
    assert agent.earlier(1) == ["Penúltima."]
    assert agent.earlier(1) == ["Penúltima."]
    assert taken == ["Última.", "Penúltima."]
    # One with nothing to say is left out.
    assert agent.earlier(2) == ["Primera."]
    assert agent.earlier(3) is None
    assert agent.earlier(0) == ["Última."]


def test_the_state_lives_in_the_runtime_dir_or_in_the_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    assert cli.state_dir() == tmp_path / "run" / "read-reply"

    monkeypatch.delenv("XDG_RUNTIME_DIR")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert cli.state_dir() == tmp_path / ".cache" / "read-reply"


@pytest.mark.parametrize(
    ("state_home", "expected"),
    [
        ("/xdg/state", "/xdg/state"),
        ("", "~/.local/state"),
        ("relative", "~/.local/state"),
    ],
    ids=["set", "unset", "relative"],
)
def test_the_speed_is_kept_in_the_state_folder(
    monkeypatch: pytest.MonkeyPatch, state_home: str, expected: str
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", state_home)

    assert cli.rate_file() == Path(expected).expanduser() / "read-reply" / "rate"
