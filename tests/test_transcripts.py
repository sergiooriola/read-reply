import json
from pathlib import Path
from typing import Any

import pytest

from read_reply.errors import UserError
from read_reply.herdr import Agent
from read_reply.transcripts import (
    agy_reply,
    claude_reply,
    codex_reply,
    last_reply,
    lines_from_end,
)


def jsonl(path: Path, *entries: dict[str, Any], tail: bytes = b"") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(json.dumps(e).encode() + b"\n" for e in entries) + tail)
    return path


def assistant(
    message_id: str, stop_reason: str | None, *content: dict[str, Any], **extra: Any
) -> dict[str, Any]:
    message = {"id": message_id, "stop_reason": stop_reason, "content": list(content)}
    return {"type": "assistant", "message": message, **extra}


def text(value: str) -> dict[str, Any]:
    return {"type": "text", "text": value}


PROMPT = {"type": "user", "message": {"role": "user", "content": "pregunta"}}
TOOL_RESULT = {"type": "user", "message": {"content": [{"type": "tool_result"}]}}

# A finished turn after a tool round, then a turn still running: a tool call
# and a line the agent is still writing.
CLAUDE_TRANSCRIPT = (
    PROMPT,
    assistant("m1", "tool_use", text("Voy a mirar.")),
    assistant("m1", "tool_use", {"type": "tool_use"}),
    TOOL_RESULT,
    assistant("m2", "end_turn", {"type": "thinking"}),
    assistant("m2", "end_turn", text("Primera parte.")),
    assistant("s1", "end_turn", text("De un subagente."), isSidechain=True),
    assistant("m2", "end_turn", text("Segunda parte.")),
    {"type": "attachment"},
    PROMPT,
    assistant("m3", "tool_use", text("Trabajando…")),
)


@pytest.mark.parametrize("block_size", [7, 64, 1 << 20])
def test_lines_from_end_yields_every_line_newest_first(
    tmp_path: Path, block_size: int
) -> None:
    path = tmp_path / "t.jsonl"
    path.write_bytes(b"uno\n\ndos\ntres largo que cruza bloques\ncuatro")

    lines = list(lines_from_end(path, block_size=block_size))

    assert lines == [b"cuatro", b"tres largo que cruza bloques", b"dos", b"uno"]


@pytest.mark.parametrize("block_size", [16, 1 << 20])
def test_claude_reply_is_the_last_message_that_ended_a_turn(
    tmp_path: Path, block_size: int
) -> None:
    path = jsonl(tmp_path / "s.jsonl", *CLAUDE_TRANSCRIPT, tail=b'{"type":"assist')

    reply = claude_reply(lines_from_end(path, block_size=block_size))

    assert reply == "Primera parte.\n\nSegunda parte."


def test_claude_reply_is_none_before_the_first_turn_ends(tmp_path: Path) -> None:
    path = jsonl(
        tmp_path / "s.jsonl", PROMPT, assistant("m1", "tool_use", text("Miro."))
    )

    assert claude_reply(lines_from_end(path)) is None


def test_codex_reply_is_the_last_task_with_a_message(tmp_path: Path) -> None:
    def task_complete(message: str | None) -> dict[str, Any]:
        payload = {"type": "task_complete", "last_agent_message": message}
        return {"type": "event_msg", "payload": payload}

    path = jsonl(
        tmp_path / "rollout.jsonl",
        task_complete("Primera tarea."),
        task_complete("Segunda tarea."),
        task_complete(None),
        task_complete(" \n"),
    )

    assert codex_reply(lines_from_end(path)) == "Segunda tarea."


def agy_step(kind: str, status: str = "DONE", **fields: Any) -> dict[str, Any]:
    return {"source": "MODEL", "type": kind, "status": status, **fields}


# An answer after a tool round, then a turn still running: a blank answer, a
# tool call with text, a tool that failed and an answer not yet done.
AGY_TRANSCRIPT = (
    {"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "pregunta"},
    agy_step("PLANNER_RESPONSE", tool_calls=[{"name": "view_file", "args": {}}]),
    agy_step("GENERIC", content="Salida de la herramienta."),
    agy_step("PLANNER_RESPONSE", content="La respuesta."),
    {"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "otra"},
    agy_step("PLANNER_RESPONSE", content=" \n"),
    agy_step(
        "PLANNER_RESPONSE",
        content="Busco.",
        tool_calls=[{"name": "grep_search", "args": {}}],
    ),
    agy_step("GENERIC", "ERROR", content="Falló la herramienta."),
    agy_step("PLANNER_RESPONSE", "RUNNING", content="A medio escribir"),
)


def test_agy_reply_is_the_last_answer_without_tool_calls(tmp_path: Path) -> None:
    path = jsonl(tmp_path / "transcript_full.jsonl", *AGY_TRANSCRIPT)

    assert agy_reply(lines_from_end(path)) == "La respuesta."


def test_agy_reply_is_none_before_the_first_answer(tmp_path: Path) -> None:
    path = jsonl(tmp_path / "transcript_full.jsonl", *AGY_TRANSCRIPT[:3])

    assert agy_reply(lines_from_end(path)) is None


def test_last_reply_finds_the_claude_transcript_of_the_session(tmp_path: Path) -> None:
    jsonl(tmp_path / ".claude/projects/-home-x/abc-123.jsonl", *CLAUDE_TRANSCRIPT)

    reply = last_reply(Agent("claude", "abc-123"), home=tmp_path)

    assert reply == "Primera parte.\n\nSegunda parte."


def test_last_reply_finds_the_codex_transcript_of_the_session(tmp_path: Path) -> None:
    payload = {"type": "task_complete", "last_agent_message": "Hecho."}
    jsonl(
        tmp_path
        / ".codex/sessions/2026/11/03/rollout-2026-11-03T23-19-24-abc-123.jsonl",
        {"type": "event_msg", "payload": payload},
    )

    assert last_reply(Agent("codex", "abc-123"), home=tmp_path) == "Hecho."


def test_last_reply_finds_the_agy_transcript_of_the_conversation(
    tmp_path: Path,
) -> None:
    logs = tmp_path / ".gemini/antigravity-cli/brain/abc-123/.system_generated/logs"
    jsonl(logs / "transcript_full.jsonl", *AGY_TRANSCRIPT)
    # The transcript beside it cuts long messages: never the one read.
    jsonl(logs / "transcript.jsonl", agy_step("PLANNER_RESPONSE", content="Cort"))

    assert last_reply(Agent("agy", "abc-123"), home=tmp_path) == "La respuesta."


@pytest.mark.parametrize(
    ("agent", "message"),
    [
        (Agent("copilot", "abc"), "Todavía no sé leer las respuestas de copilot."),
        (
            Agent("claude", "abc"),
            "No encuentro la conversación de claude de este panel.",
        ),
        (Agent("claude", "../abc"), "Herdr da una sesión que no entiendo: ../abc"),
    ],
)
def test_last_reply_explains_what_it_cannot_read(
    tmp_path: Path, agent: Agent, message: str
) -> None:
    with pytest.raises(UserError, match=message.replace(".", r"\.")):
        last_reply(agent, home=tmp_path)


def test_last_reply_explains_a_session_without_a_finished_reply(tmp_path: Path) -> None:
    jsonl(tmp_path / ".claude/projects/-home-x/abc.jsonl", PROMPT)

    with pytest.raises(UserError, match="todavía no ha terminado ninguna respuesta"):
        last_reply(Agent("claude", "abc"), home=tmp_path)


def test_claude_reply_skips_blank_messages(tmp_path: Path) -> None:
    path = jsonl(
        tmp_path / "s.jsonl",
        PROMPT,
        assistant("m1", "end_turn", text("Hecho.")),
        PROMPT,
        {
            "type": "assistant",
            "message": {"id": "m2", "stop_reason": "end_turn", "content": " "},
        },
        assistant("m3", "end_turn", text("\n\n")),
    )

    assert claude_reply(lines_from_end(path)) == "Hecho."


def test_a_last_line_cut_inside_a_character_is_skipped(tmp_path: Path) -> None:
    cut = json.dumps(assistant("m2", "end_turn", text("Más")), ensure_ascii=False)
    cut_bytes = cut.encode()[: cut.encode().index("á".encode()) + 1]
    path = jsonl(
        tmp_path / "s.jsonl",
        PROMPT,
        assistant("m1", "end_turn", text("Hecho.")),
        tail=cut_bytes,
    )

    assert claude_reply(lines_from_end(path)) == "Hecho."


def test_last_reply_follows_the_agents_data_variables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-data"))
    jsonl(tmp_path / "claude-data/projects/-home-x/abc.jsonl", *CLAUDE_TRANSCRIPT)

    reply = last_reply(Agent("claude", "abc"), home=tmp_path / "elsewhere")

    assert reply == "Primera parte.\n\nSegunda parte."
