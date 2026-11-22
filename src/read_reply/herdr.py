"""Herdr: the agent in a pane, and notifications."""

import json
import os
import subprocess
from contextlib import suppress
from dataclasses import dataclass

from read_reply.errors import UserError


@dataclass(frozen=True)
class Agent:
    kind: str
    """Herdr's label for the agent, such as "claude" or "codex"."""
    session: str
    """The agent's own session id, as its Herdr integration reports it."""


def herdr_bin() -> str:
    # Herdr passes its own path to the commands its keys run.
    return os.environ.get("HERDR_BIN_PATH") or "herdr"


def agent_in(pane: str) -> Agent:
    """The agent in the pane, from `herdr agent get`."""
    try:
        result = subprocess.run(
            [herdr_bin(), "agent", "get", pane],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as error:
        raise UserError("No encuentro Herdr.") from error
    if result.returncode != 0:
        if "agent_not_found" in result.stdout + result.stderr:
            raise UserError("El panel activo no tiene ningún agente.")
        details = (result.stderr or result.stdout).strip()
        raise UserError(f"Herdr no responde: {details}")
    agent = json.loads(result.stdout)["result"]["agent"]
    session = (agent.get("agent_session") or {}).get("value")
    if not session:
        raise UserError("Herdr todavía no sabe qué conversación tiene este agente.")
    return Agent(kind=agent["agent"], session=session)


def notify(title: str, body: str) -> None:
    """A Herdr notification, delivered as Herdr's [ui.toast] config says."""
    with suppress(FileNotFoundError):  # the message is also on stderr
        subprocess.run(
            [herdr_bin(), "notification", "show", title, "--body", body],
            capture_output=True,
            check=False,
        )
