"""Markdown turned into paragraphs meant for the ear.

markdown-it-py parses the Markdown as GitHub does; walking its syntax tree
drops the marks, announces code blocks instead of spelling them out, reads
tables row by row and links by their text.
"""

import re
from collections.abc import Iterator
from urllib.parse import urlsplit

from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode
from mdit_py_plugins.gfm import gfm_plugin

CODE_BLOCK_NOTICE = "Bloque de código omitido."
# Longer paragraphs are spoken sentence by sentence, so that no single request
# to the online voice carries minutes of audio.
MAX_CHUNK_CHARS = 400

# GitHub Flavored Markdown, which is what the agents write. Raw HTML is parsed
# as such so that it can be left out instead of read. No $math$: it would take
# the text between two prices in dollars, "0,99 $ de 5 $", for a formula.
PARSER = MarkdownIt("commonmark", {"html": True}).use(gfm_plugin)


def speech_chunks(markdown: str) -> list[str]:
    """The reply as the pieces of text to speak, in order."""
    tree = SyntaxTreeNode(PARSER.parse(markdown))
    paragraphs = [text for text in spoken_blocks(tree.children) if text]
    return [chunk for paragraph in paragraphs for chunk in split_sentences(paragraph)]


def spoken_blocks(blocks: list[SyntaxTreeNode]) -> Iterator[str]:
    """One string per paragraph to speak, from the block nodes."""
    for block in blocks:
        match block.type:
            case "paragraph" | "heading" | "alert_title":
                yield spoken_inlines(block.children)
            case "fence" | "code_block":
                yield CODE_BLOCK_NOTICE
            case "table":
                yield from spoken_table(block)
            case "footnote_block":
                pass  # the notes are left out of the reading
            case _:  # lists, quotes and alerts hold blocks; rules and raw HTML, none
                yield from spoken_blocks(block.children)


def spoken_table(table: SyntaxTreeNode) -> Iterator[str]:
    """One sentence per row, header included, cells separated by commas."""
    for section in table.children:  # the head, then the body
        for row in section.children:
            texts = (spoken_inlines(cell.children) for cell in row.children)
            text = ", ".join(filter(None, texts))
            if text:
                yield text if text.endswith((".", "!", "?", "…")) else text + "."


def spoken_inlines(inlines: list[SyntaxTreeNode]) -> str:
    parts: list[str] = []
    for inline in inlines:
        match inline.type:
            case "text" | "code_inline":
                parts.append(inline.content)
            case "softbreak" | "hardbreak":
                parts.append(" ")
            case "link":
                parts.append(spoken_link(inline))
            case "html_inline" | "footnote_ref":
                pass  # tags and note marks are not read
            case _:  # emphasis, strikethrough, images: their text
                parts.append(spoken_inlines(inline.children))
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def spoken_link(link: SyntaxTreeNode) -> str:
    """The link text, or just the site when the text is the address itself."""
    text, url = spoken_inlines(link.children), str(link.attrs["href"])
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
