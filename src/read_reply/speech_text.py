"""Markdown turned into paragraphs meant for the ear, and text copied from the
terminal too.

markdown-it-py parses the Markdown as GitHub does; walking its syntax tree
drops the marks, announces code blocks instead of spelling them out, reads
tables row by row and links by their text.
"""

import re
import textwrap
from collections.abc import Iterator
from contextlib import suppress
from urllib.parse import urlsplit

from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode
from mdit_py_plugins.gfm import gfm_plugin

CODE_BLOCK_NOTICE = "Bloque de código omitido."
# Longer paragraphs are spoken sentence by sentence, so that no single request
# to the online voice carries minutes of audio.
MAX_CHUNK_CHARS = 400
# GitHub's alerts, by the names its documentation in Spanish gives them.
ALERT_TITLES = {
    "NOTE": "Nota",
    "TIP": "Sugerencia",
    "IMPORTANT": "Importante",
    "WARNING": "Advertencia",
    "CAUTION": "Precaución",
}
# What the agents put on screen before each message, and Codex before each
# list item too: ● in Claude Code, • in Codex.
SCREEN_MARK = re.compile(r"^([ \t]*)[●•] ", re.MULTILINE)


class SpeechParser(MarkdownIt):
    """GitHub Flavored Markdown, which is what the agents write, parsed to be read.

    Raw HTML is parsed as such so that it can be left out instead of read. No
    $math$: it would take the text between two prices in dollars,
    "0,99 $ de 5 $", for a formula.

    For text copied from the screen, there is neither HTML nor code: a <panel>
    or a ``` line on screen is text to read.
    """

    def __init__(self, *, screen: bool = False) -> None:
        # CommonMark's nesting limit, 20, drops everything after a list ten
        # levels deep.
        super().__init__("commonmark", {"html": not screen, "maxNesting": 100})
        self.use(gfm_plugin)
        # The notes stay where they are written, to be skipped: moving them to
        # the end, as a web page does, fails on a note in a quote in a note.
        self.disable("footnote_tail")
        if screen:
            self.disable(["code", "fence"])

    def validateLink(self, url: str) -> bool:
        """Every link is valid here: none is rendered or followed, only read."""
        return True


REPLY_PARSER = SpeechParser()
SCREEN_PARSER = SpeechParser(screen=True)


def speech_chunks(markdown: str) -> list[str]:
    """The reply as the pieces of text to speak, in order."""
    return chunks_of(REPLY_PARSER, markdown)


def screen_chunks(text: str) -> list[str]:
    """Text copied from the terminal as the pieces of text to speak, in order.

    The screen shows the reply already rendered, which is near enough to
    Markdown: its lists keep their dashes and numbers, so each item is still a
    piece of its own, and the lines cut at the window's width join again. The
    agents' marks before a message or an item become dashes.

    The indent tells an item's next paragraph from the next item, or a number
    the window cut before from a step, so it stays, but for what every line
    has in common: a selection that starts in a nested list still starts a
    list.
    """
    return chunks_of(SCREEN_PARSER, SCREEN_MARK.sub(r"\1- ", textwrap.dedent(text)))


def chunks_of(parser: SpeechParser, text: str) -> list[str]:
    tree = SyntaxTreeNode(parser.parse(text))
    paragraphs = [block for block in spoken_blocks(tree.children) if block]
    return [chunk for paragraph in paragraphs for chunk in split_sentences(paragraph)]


def spoken_blocks(blocks: list[SyntaxTreeNode]) -> Iterator[str]:
    """One string per paragraph to speak, from the block nodes."""
    for block in blocks:
        match block.type:
            case "paragraph" | "heading":
                yield spoken_inlines(block.children)
            case "fence" | "code_block":
                yield CODE_BLOCK_NOTICE
            case "table":
                yield from spoken_table(block)
            case "alert":  # its own title is GitHub's, in English
                yield ALERT_TITLES.get(str(block.meta.get("kind")), "")
                yield from spoken_blocks(block.children)
            case "alert_title" | "footnote_reference":
                pass  # said above; the notes are left out of the reading
            case _:  # lists and quotes hold blocks; rules and raw HTML, none
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
            case "text" | "text_special" | "code_inline":
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
    """The link text, or just the site when the whole text is an address.

    The site comes from the text as written: the destination is encoded for a
    web page, with "españa.es" as "xn--espaa-rta.es".
    """
    text = spoken_inlines(link.children)
    if re.fullmatch(r"\S+://\S+", text):
        with suppress(ValueError):  # not a valid address after all
            return urlsplit(text).hostname or text
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
