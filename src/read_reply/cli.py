"""The read-reply command, meant for Herdr keys.

Herdr passes the pane that was focused when the key was pressed in
HERDR_ACTIVE_PANE_ID. A press reads the last reply of the agent in it, or
with --clipboard the text copied, such as a part of the reply selected with
the mouse; a press while it is reading stops it. A key has no terminal, so
errors also show up as Herdr notifications.
"""

import argparse
import fcntl
import os
import sys
from collections.abc import Callable
from functools import partial
from pathlib import Path

from read_reply import herdr
from read_reply.errors import UserError
from read_reply.herdr import agent_in
from read_reply.player import Player, request_stop
from read_reply.speech_text import screen_chunks, speech_chunks
from read_reply.transcripts import last_reply
from read_reply.windows import clipboard_text

NOTIFICATION_TITLE = "Leer respuesta"


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    chunks = clipboard_chunks if args.clipboard else partial(reply_chunks, args.pane)
    try:
        if args.print:
            print("\n\n".join(chunks()))
        else:
            read_or_stop(chunks, state_dir(), rate_file())
    except UserError as error:
        notify(str(error))
        sys.exit(1)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="read-reply",
        description="Lee en voz alta la última respuesta del agente del panel activo "
        "de Herdr, o lo copiado; si ya está leyendo, para.",
    )
    parser.add_argument(
        "--pane",
        default=os.environ.get("HERDR_ACTIVE_PANE_ID"),
        help="panel de Herdr (por defecto, HERDR_ACTIVE_PANE_ID, "
        "que Herdr pasa a sus atajos)",
    )
    parser.add_argument(
        "--clipboard",
        action="store_true",
        help="lee el texto copiado en Windows, como el que seleccionas con el ratón "
        "en el terminal, en vez de la respuesta",
    )
    parser.add_argument(
        "--print", action="store_true", help="escribe el texto que leería, sin leerlo"
    )
    args = parser.parse_args(argv)
    if not args.pane and not args.clipboard:
        parser.error("falta --pane: fuera de un atajo de Herdr no sé qué panel leer")
    return args


def reply_chunks(pane: str) -> list[str]:
    chunks = speech_chunks(last_reply(agent_in(pane)))
    if not chunks:
        raise UserError("La respuesta no tiene texto que leer.")
    return chunks


def clipboard_chunks() -> list[str]:
    chunks = screen_chunks(clipboard_text())
    if not chunks:
        raise UserError("No hay texto copiado que leer.")
    return chunks


def read_or_stop(chunks: Callable[[], list[str]], state: Path, rate: Path) -> None:
    """Reads the chunks, or stops the reading in progress if there is one.

    They are prepared once a second press can stop the reading, while the
    desktop script looks for the terminal.
    """
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (state / "lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            request_stop(state)
            return
        with Player(state, rate) as player:
            text = chunks()
            if not player.stop_requested:
                player.play(text)


def state_dir() -> Path:
    """Where the lock and the stop address of the reading in progress live."""
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    # Without one, a folder of the person's own: a shared /tmp is not safe.
    return (
        Path(runtime) / "read-reply"
        if runtime
        else Path.home() / ".cache" / "read-reply"
    )


def rate_file() -> Path:
    """Where the speed chosen in the window is kept between readings."""
    state = os.environ.get("XDG_STATE_HOME", "")
    # The XDG Base Directory spec: a relative path is to be ignored.
    home = Path(state) if Path(state).is_absolute() else Path.home() / ".local/state"
    return home / "read-reply" / "rate"


def notify(message: str) -> None:
    print(f"read-reply: {message}", file=sys.stderr)
    if not sys.stderr.isatty():
        herdr.notify(NOTIFICATION_TITLE, message)
