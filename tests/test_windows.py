"""Reading the Windows clipboard. PowerShell itself runs only on Windows: see
the README."""

from collections.abc import Callable

import pytest

from read_reply import windows
from read_reply.errors import UserError
from read_reply.windows import clipboard_text


def test_the_clipboard_is_read_in_utf_8_with_unix_line_ends(
    fake_powershell: Callable[[str], None],
) -> None:
    fake_powershell("printf 'Línea «uno»\\r\\nLínea dos'\n")

    assert clipboard_text() == "Línea «uno»\nLínea dos"


def test_a_clipboard_without_text_reads_as_empty(
    fake_powershell: Callable[[str], None],
) -> None:
    fake_powershell("exit 0\n")

    assert clipboard_text() == ""


@pytest.mark.parametrize("fails", [True, False], ids=["fails", "missing"])
def test_without_the_clipboard_it_explains(
    fake_powershell: Callable[[str], None], fails: bool
) -> None:
    if fails:  # its message in the console's code page, CP850: "Excepción"
        fake_powershell("printf 'Excepci\\242n' >&2\nexit 1\n")

    with pytest.raises(UserError, match="No puedo leer el portapapeles"):
        clipboard_text()


def test_a_clipboard_that_hangs_is_waited_for_briefly(
    monkeypatch: pytest.MonkeyPatch, fake_powershell: Callable[[str], None]
) -> None:
    fake_powershell("exec sleep 30\n")
    monkeypatch.setattr(windows, "CLIPBOARD_TIMEOUT_S", 0.2)

    with pytest.raises(UserError, match="no responde"):
        clipboard_text()
