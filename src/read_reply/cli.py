"""The read-reply command, meant for a Herdr key.

Herdr passes the pane that was focused when the key was pressed in
HERDR_ACTIVE_PANE_ID. A press reads the last reply of the agent in it; a
press while it is reading stops it. A key has no terminal, so errors also
show up as Herdr notifications.
"""

import argparse
import fcntl
import os
import sys
from pathlib import Path

from read_reply import herdr
from read_reply.errors import UserError
from read_reply.herdr import agent_in
from read_reply.player import Player, request_stop
from read_reply.speech_text import speech_chunks
from read_reply.transcripts import last_reply

NOTIFICATION_TITLE = "Leer respuesta"


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        if args.print:
            print("\n\n".join(reply_chunks(args.pane)))
        else:
            read_or_stop(args.pane, state_dir(), rate_file())
    except UserError as error:
        notify(str(error))
        sys.exit(1)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="read-reply",
        description="Lee en voz alta la última respuesta del agente del panel activo "
        "de Herdr; si ya está leyendo, para.",
    )
    parser.add_argument(
        "--pane",
        default=os.environ.get("HERDR_ACTIVE_PANE_ID"),
        help="panel de Herdr (por defecto, HERDR_ACTIVE_PANE_ID, "
        "que Herdr pasa a sus atajos)",
    )
    parser.add_argument(
        "--print", action="store_true", help="escribe el texto que leería, sin leerlo"
    )
    args = parser.parse_args(argv)
    if not args.pane:
        parser.error("falta --pane: fuera de un atajo de Herdr no sé qué panel leer")
    return args


def reply_chunks(pane: str) -> list[str]:
    chunks = speech_chunks(last_reply(agent_in(pane)))
    if not chunks:
        raise UserError("La respuesta no tiene texto que leer.")
    return chunks


def read_or_stop(pane: str, state: Path, rate: Path) -> None:
    """Reads the reply, or stops the reading in progress if there is one."""
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (state / "lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            request_stop(state)
            return
        with Player(state, rate) as player:
            chunks = reply_chunks(pane)
            if not player.stop_requested:
                player.play(chunks)


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
