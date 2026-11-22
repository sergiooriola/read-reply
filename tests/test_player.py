"""The page's server. Edge itself runs only on Windows: see the README."""

import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from read_reply.player import STOP_URL_FILE, VOICES, Player, request_stop


def get(url: str) -> bytes:
    with urlopen(url, timeout=5) as response:
        body: bytes = response.read()
        return body


def post(url: str, body: bytes = b"") -> None:
    urlopen(Request(url, data=body, method="POST"), timeout=5).close()


def test_the_page_and_the_reply_are_served_under_a_secret_path(tmp_path: Path) -> None:
    with Player(tmp_path) as player:
        player._chunks = ["Hola."]

        page = get(player.url)
        reply = json.loads(get(player.url + "reply"))

    assert b"speechSynthesis" in page
    assert reply == {"chunks": ["Hola."], "voices": list(VOICES), "rate": 1.0}


def test_other_paths_are_not_found(tmp_path: Path) -> None:
    with Player(tmp_path) as player:
        root = player.url.rsplit("/", 2)[0] + "/"
        with pytest.raises(HTTPError, match="404"):
            get(root + "reply")


def test_a_second_press_stops_the_reading(tmp_path: Path) -> None:
    with Player(tmp_path) as player:
        assert (tmp_path / STOP_URL_FILE).read_text() == player.url + "stop"

        request_stop(tmp_path)

        assert player.stop_requested
        assert json.loads(get(player.url + "state")) == {"stop": True}
    assert not (tmp_path / STOP_URL_FILE).exists()


def test_a_stop_without_a_reading_does_nothing(tmp_path: Path) -> None:
    request_stop(tmp_path)


def test_the_page_reports_errors_and_its_end(tmp_path: Path) -> None:
    with Player(tmp_path) as player:
        post(player.url + "error", b"network")
        post(player.url + "finished")

        assert player._errors == ["network"]
        assert player._finished.is_set()
