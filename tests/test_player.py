"""The page's server. Edge itself runs only on Windows: see the README."""

import json
import threading
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from read_reply import player as player_module
from read_reply.desktop import Terminal
from read_reply.errors import UserError
from read_reply.player import (
    STOP_URL_FILE,
    VOICES,
    Player,
    edge_command,
    request_stop,
    saved_rate,
)


def get(url: str) -> bytes:
    with urlopen(url, timeout=5) as response:
        body: bytes = response.read()
        return body


def post(url: str, body: bytes = b"") -> None:
    urlopen(Request(url, data=body, method="POST"), timeout=5).close()


def test_the_page_and_the_reply_are_served_under_a_secret_path(tmp_path: Path) -> None:
    with Player(tmp_path, tmp_path / "rate") as player:
        player._chunks = ["Hola."]

        page = get(player.url)
        reply = json.loads(get(player.url + "reply"))

    assert b"speechSynthesis" in page
    assert reply == {"chunks": ["Hola."], "voices": list(VOICES), "rate": 1.0}


def test_the_speed_chosen_in_one_reading_comes_back_in_the_next(
    tmp_path: Path,
) -> None:
    rate_file = tmp_path / "state" / "rate"
    with Player(tmp_path, rate_file) as player:
        post(player.url + "rate", b"1.3")

    with Player(tmp_path, rate_file) as player:
        reply = json.loads(get(player.url + "reply"))

    assert reply["rate"] == 1.3


@pytest.mark.parametrize("body", [b"rapido", b"nan", b"0", b"11"])
def test_a_speed_that_is_not_one_is_refused(tmp_path: Path, body: bytes) -> None:
    with (
        Player(tmp_path, tmp_path / "rate") as player,
        pytest.raises(HTTPError, match="400"),
    ):
        post(player.url + "rate", body)

    assert not (tmp_path / "rate").exists()


@pytest.mark.parametrize("content", ["", "rapido", "50"])
def test_an_unreadable_speed_is_the_normal_one(tmp_path: Path, content: str) -> None:
    (tmp_path / "rate").write_text(content)

    assert saved_rate(tmp_path / "rate") == 1.0


def test_the_page_gets_its_module_as_javascript(tmp_path: Path) -> None:
    with (
        Player(tmp_path, tmp_path / "rate") as player,
        urlopen(player.url + "reading.mjs", timeout=5) as response,
    ):
        assert response.headers["Content-Type"].startswith("text/javascript")
        assert b"export class Reading" in response.read()


def test_other_paths_are_not_found(tmp_path: Path) -> None:
    with Player(tmp_path, tmp_path / "rate") as player:
        root = player.url.rsplit("/", 2)[0] + "/"
        with pytest.raises(HTTPError, match="404"):
            get(root + "reply")


def test_a_second_press_stops_the_reading(tmp_path: Path) -> None:
    with Player(tmp_path, tmp_path / "rate") as player:
        assert (tmp_path / STOP_URL_FILE).read_text() == player.url + "stop"

        request_stop(tmp_path)

        assert player.stop_requested
        assert json.loads(get(player.url + "state")) == {"stop": True}
    assert not (tmp_path / STOP_URL_FILE).exists()


def test_a_stop_without_a_reading_does_nothing(tmp_path: Path) -> None:
    request_stop(tmp_path)


def test_the_page_reports_errors_and_its_end(tmp_path: Path) -> None:
    with Player(tmp_path, tmp_path / "rate") as player:
        post(player.url + "error", b"network")
        post(player.url + "finished")

        assert player._errors == ["network"]
        assert player._finished.is_set()


def test_a_stop_reaches_the_player_despite_a_proxy_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    monkeypatch.setenv("no_proxy", "")

    with Player(tmp_path, tmp_path / "rate") as player:
        request_stop(tmp_path)

        assert player.stop_requested


@pytest.mark.parametrize("content", ["", "   \n"])
def test_a_stop_with_a_half_written_address_does_nothing(
    tmp_path: Path, content: str
) -> None:
    (tmp_path / STOP_URL_FILE).write_text(content)

    request_stop(tmp_path, wait_s=0.1)


def test_a_stop_waits_a_moment_for_a_reading_that_is_starting(tmp_path: Path) -> None:
    player = Player(tmp_path, tmp_path / "rate")
    starting = threading.Timer(0.2, player.__enter__)
    starting.start()
    try:
        request_stop(tmp_path)

        assert player.stop_requested
    finally:
        starting.join()
        player.__exit__(None, None, None)


class FakeEdge:
    """A process that has exited, or not, as the test says."""

    def __init__(self, exited: bool) -> None:
        self.exited = exited

    def poll(self) -> int | None:
        return 0 if self.exited else None

    def wait(self, timeout: float | None = None) -> int:
        return 0


def test_waiting_ends_when_the_page_finishes(tmp_path: Path) -> None:
    with Player(tmp_path, tmp_path / "rate") as player:
        get(player.url)
        post(player.url + "finished")

        player.wait_for(FakeEdge(exited=True))


def test_edge_closing_before_the_end_is_an_error(tmp_path: Path) -> None:
    with Player(tmp_path, tmp_path / "rate") as player:
        get(player.url)

        with pytest.raises(UserError, match="antes de terminar"):
            player.wait_for(FakeEdge(exited=True))


def test_edge_closing_after_a_stop_is_not_an_error(tmp_path: Path) -> None:
    with Player(tmp_path, tmp_path / "rate") as player:
        get(player.url)
        request_stop(tmp_path)

        player.wait_for(FakeEdge(exited=True))


def test_a_stop_before_the_page_loads_ends_the_wait_at_once(tmp_path: Path) -> None:
    with Player(tmp_path, tmp_path / "rate") as player:
        request_stop(tmp_path)
        start = time.monotonic()

        player.wait_for(FakeEdge(exited=False))

        assert time.monotonic() - start < 1


def test_a_page_that_never_loads_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(player_module, "EDGE_START_TIMEOUT_S", 0.3)

    with (
        Player(tmp_path, tmp_path / "rate") as player,
        pytest.raises(UserError, match="no ha arrancado"),
    ):
        player.wait_for(FakeEdge(exited=False))


def test_a_page_that_ignores_a_stop_is_given_up_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(player_module, "STOP_GRACE_S", 0.3)

    with Player(tmp_path, tmp_path / "rate") as player:
        get(player.url)
        request_stop(tmp_path)

        player.wait_for(FakeEdge(exited=False))


def test_edge_opens_the_page_as_a_small_window_over_the_terminal() -> None:
    terminal = Terminal(0, 0, 1920, monitor_left=0, monitor_top=0, scale=1.0)

    command = edge_command("http://127.0.0.1:1/x/", "C:\\profile", terminal)

    assert "--app=http://127.0.0.1:1/x/" in command
    assert "--window-size=300,110" in command
    assert "--window-position=810,8" in command
    assert "--user-data-dir=C:\\profile" in command
    assert "--headless" not in command


def test_without_the_terminal_edge_places_the_window() -> None:
    command = edge_command("http://127.0.0.1:1/x/", "C:\\profile", None)

    assert not any(arg.startswith("--window-position") for arg in command)
