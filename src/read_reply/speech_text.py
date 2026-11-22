"""Markdown turned into paragraphs meant for the ear.

pandoc parses the Markdown; walking its syntax tree drops the marks, announces
code blocks instead of spelling them out, reads tables row by row and links
by their text.
"""

import json
import re
import subprocess
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlsplit

from read_reply.errors import UserError

type Node = dict[str, Any]

CODE_BLOCK_NOTICE = "Bloque de código omitido."
# Longer paragraphs are spoken sentence by sentence, so that no single request
# to the online voice carries minutes of audio.
MAX_CHUNK_CHARS = 400


def speech_chunks(markdown: str) -> list[str]:
    """The reply as the pieces of text to speak, in order."""
    try:
        result = subprocess.run(
            ["pandoc", "--from", "gfm", "--to", "json"],
            input=markdown,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as error:
        raise UserError(
            "Falta pandoc, que hace falta para leer el Markdown."
        ) from error
    if result.returncode != 0:
        raise UserError(
            f"pandoc no ha podido leer la respuesta: {result.stderr.strip()}"
        )
    blocks: list[Node] = json.loads(result.stdout)["blocks"]
    paragraphs = [text for text in spoken_blocks(blocks) if text]
    return [chunk for paragraph in paragraphs for chunk in split_sentences(paragraph)]


# One branch per kind of block is the clearest way to walk the tree.
def spoken_blocks(blocks: list[Node]) -> Iterator[str]:  # noqa: PLR0912
    """One string per paragraph to speak, from pandoc's block nodes."""
    for block in blocks:
        kind: str = block["t"]
        content: Any = block.get("c")
        match kind:
            case "Para" | "Plain":
                yield spoken_inlines(content)
            case "Header":
                yield spoken_inlines(content[2])
            case "BulletList":
                for item in content:
                    yield from spoken_blocks(item)
            case "OrderedList":
                for item in content[1]:
                    yield from spoken_blocks(item)
            case "BlockQuote":
                yield from spoken_blocks(content)
            case "Div":
                yield from spoken_blocks(content[1])
            case "LineBlock":
                yield " ".join(spoken_inlines(line) for line in content)
            case "DefinitionList":
                for term, definitions in content:
                    yield spoken_inlines(term)
                    for definition in definitions:
                        yield from spoken_blocks(definition)
            case "CodeBlock":
                yield CODE_BLOCK_NOTICE
            case "Table":
                yield from spoken_table(content)
            case _:  # HorizontalRule, RawBlock (HTML), Figure: nothing to say
                pass


def spoken_table(table: list[Any]) -> Iterator[str]:
    """One sentence per row, header included, cells separated by commas."""
    _attr, _caption, _colspecs, head, bodies, foot = table
    rows = list(head[1])
    for body in bodies:
        rows += body[2] + body[3]  # intermediate head rows, then body rows
    rows += foot[1]
    for _row_attr, cells in rows:
        texts = (" ".join(filter(None, spoken_blocks(cell[4]))) for cell in cells)
        row = ", ".join(filter(None, texts))
        if row:
            yield row if row.endswith((".", "!", "?", "…")) else row + "."


def spoken_inlines(inlines: list[Node]) -> str:
    parts: list[str] = []
    for inline in inlines:
        kind: str = inline["t"]
        content: Any = inline.get("c")
        match kind:
            case "Str":
                parts.append(content)
            case "Space" | "SoftBreak" | "LineBreak":
                parts.append(" ")
            case "Code" | "Math":
                parts.append(content[1])
            case (
                "Emph"
                | "Strong"
                | "Underline"
                | "Strikeout"
                | "Superscript"
                | "Subscript"
                | "SmallCaps"
            ):
                parts.append(spoken_inlines(content))
            case "Quoted" | "Cite" | "Span" | "Image":
                parts.append(spoken_inlines(content[1]))
            case "Link":
                parts.append(spoken_link(content))
            case _:  # RawInline (HTML), Note
                pass
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def spoken_link(link: list[Any]) -> str:
    """The link text, or just the site when the text is the address itself."""
    text, url = spoken_inlines(link[1]), link[2][0]
    if text in (url, url.removeprefix("mailto:")) or text.startswith(
        ("http://", "https://")
    ):
        return urlsplit(url).hostname or text
    return text


def split_sentences(paragraph: str) -> list[str]:
    """The paragraph in pieces of up to MAX_CHUNK_CHARS, cut between sentences."""
    if len(paragraph) <= MAX_CHUNK_CHARS:
        return [paragraph]
    chunks: list[str] = []
    for sentence in re.split(r"(?<=[.!?…:;])\s+", paragraph):
        if chunks and len(chunks[-1]) + 1 + len(sentence) <= MAX_CHUNK_CHARS:
            chunks[-1] += " " + sentence
        else:
            chunks.append(sentence)
    return chunks
