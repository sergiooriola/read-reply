"""The replies of an agent session, read from its transcript, newest first.

Transcripts grow to hundreds of megabytes, so they are read from the end and
only as far back as the replies asked for.
"""

import json
import os
import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from read_reply.errors import UserError
from read_reply.herdr import Agent

type Extractor = Callable[[Iterator[bytes]], Iterator[str]]

# Session ids go into a file pattern, so anything else is refused.
SESSION_ID = re.compile(r"[0-9A-Za-z][0-9A-Za-z_-]*")


def replies(agent: Agent, home: Path | None = None) -> Iterator[str]:
    """The finished replies of the agent, newest first, as the Markdown it wrote.

    The transcript is found at once, and read as the replies are taken.
    """
    home = home or Path.home()
    # The same variables that move the data of each agent.
    claude_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR") or home / ".claude")
    codex_dir = Path(os.environ.get("CODEX_HOME") or home / ".codex")
    # agy has no such variable, nor a documented place for its data.
    agy_dir = home / ".gemini" / "antigravity-cli"
    sources: dict[str, tuple[Path, str, Extractor]] = {
        # ~/.claude/projects/<project>/<session>.jsonl
        "claude": (claude_dir / "projects", "*/{}.jsonl", claude_replies),
        # ~/.codex/sessions/<year>/<month>/<day>/rollout-<time>-<session>.jsonl
        "codex": (
            codex_dir / "sessions",
            "*/*/*/rollout-*-{}.jsonl",
            codex_replies,
        ),
        # ~/.gemini/antigravity-cli/brain/<conversation>/.system_generated/logs/
        # transcript_full.jsonl; transcript.jsonl beside it cuts long messages.
        "agy": (
            agy_dir / "brain",
            "{}/.system_generated/logs/transcript_full.jsonl",
            agy_replies,
        ),
    }
    if agent.kind not in sources:
        raise UserError(f"Todavía no sé leer las respuestas de {agent.kind}.")
    if not SESSION_ID.fullmatch(agent.session):
        raise UserError(f"Herdr da una sesión que no entiendo: {agent.session}")
    root, pattern, extract = sources[agent.kind]
    transcript = next(root.glob(pattern.format(agent.session)), None)
    if transcript is None:
        raise UserError(f"No encuentro la conversación de {agent.kind} de este panel.")
    return extract(lines_from_end(transcript))


def lines_from_end(path: Path, block_size: int = 1 << 20) -> Iterator[bytes]:
    """The non-empty lines of a file, last line first, read in blocks."""
    with path.open("rb") as file:
        position = file.seek(0, os.SEEK_END)
        partial = b""
        while position > 0:
            step = min(block_size, position)
            position -= step
            file.seek(position)
            lines = (file.read(step) + partial).split(b"\n")
            partial = lines.pop(0)  # may continue in the previous block
            yield from (line for line in reversed(lines) if line.strip())
        if partial.strip():
            yield partial


def claude_replies(lines: Iterator[bytes]) -> Iterator[str]:
    """The assistant messages that ended a turn, from lines newest first.

    A message spans several lines that share its id (thinking, text, tool
    calls), and the one that ends a turn does not stop for a tool.
    """
    message_id: str | None = None  # of the reply being gathered
    texts: list[str] = []
    for line in lines:
        if b'"assistant"' not in line and b'"user"' not in line:
            continue  # cheap filter before parsing
        entry = parse_json(line)
        if (
            entry is None
            or entry.get("type") not in ("assistant", "user")
            or entry.get("isSidechain")
        ):
            continue
        message = entry.get("message") or {}
        if message_id is not None:
            if entry["type"] == "assistant" and message.get("id") == message_id:
                texts = message_texts(message) + texts
                continue
            yield "\n\n".join(texts)  # an older entry: the reply is whole
            message_id, texts = None, []
        ends_turn = message.get("stop_reason") not in (None, "tool_use")
        if entry["type"] == "assistant" and ends_turn and message_texts(message):
            message_id, texts = message.get("id"), message_texts(message)
    if message_id is not None:
        yield "\n\n".join(texts)


def message_texts(message: dict[str, Any]) -> list[str]:
    content = message.get("content")
    if isinstance(content, str):
        return [content] if content.strip() else []
    return [
        part["text"]
        for part in content or []
        if part.get("type") == "text" and str(part.get("text") or "").strip()
    ]


def codex_replies(lines: Iterator[bytes]) -> Iterator[str]:
    """The last agent message of each finished task, from lines newest first."""
    for line in lines:
        if b'"task_complete"' not in line:
            continue
        entry = parse_json(line) or {}
        payload = entry.get("payload") or {}
        ends_task = (
            entry.get("type") == "event_msg" and payload.get("type") == "task_complete"
        )
        message = str(payload.get("last_agent_message") or "")
        if ends_task and message.strip():
            yield message


def agy_replies(lines: Iterator[bytes]) -> Iterator[str]:
    """The finished answers of the model, from lines newest first.

    Each step of the conversation is a line. An answer is a planner step with
    text and no tool calls; the planner steps that call tools carry no text.
    """
    for line in lines:
        if b'"PLANNER_RESPONSE"' not in line:
            continue
        entry = parse_json(line) or {}
        answers = (
            entry.get("type") == "PLANNER_RESPONSE"
            and entry.get("status") == "DONE"
            and not entry.get("tool_calls")
        )
        content = str(entry.get("content") or "")
        if answers and content.strip():
            yield content


def parse_json(line: bytes) -> dict[str, Any] | None:
    try:
        value = json.loads(line)
    except ValueError:  # bad JSON or bad UTF-8
        return None  # e.g. a line the agent is still writing
    return value if isinstance(value, dict) else None
