import pytest

from read_reply.speech_text import (
    CODE_BLOCK_NOTICE,
    MAX_CHUNK_CHARS,
    speech_chunks,
    split_sentences,
)


def test_markdown_marks_are_not_spoken() -> None:
    markdown = "Texto con **negrita**, _cursiva_, `código` y ~~tachado~~."

    assert speech_chunks(markdown) == ["Texto con negrita, cursiva, código y tachado."]


def test_links_are_read_by_their_text_or_their_site() -> None:
    markdown = "Mira [la guía](https://example.com/a/b) y https://github.com/x/y."

    assert speech_chunks(markdown) == ["Mira la guía y github.com."]


def test_code_blocks_are_announced_not_spelled_out() -> None:
    markdown = "Antes.\n\n```bash\necho hola\n```\n\nDespués."

    assert speech_chunks(markdown) == ["Antes.", CODE_BLOCK_NOTICE, "Después."]


def test_tables_are_read_row_by_row() -> None:
    markdown = "| Opción | Nota |\n|---|---|\n| Uno | Bien. |\n| Dos | |\n"

    assert speech_chunks(markdown) == ["Opción, Nota.", "Uno, Bien.", "Dos."]


def test_empty_cells_leave_no_gaps() -> None:
    markdown = "| A | B | C |\n|---|---|---|\n| Uno | | Tres |\n"

    assert speech_chunks(markdown) == ["A, B, C.", "Uno, Tres."]


def test_headings_and_list_items_are_separate_chunks() -> None:
    markdown = "# Título\n\n- Primero\n- Segundo\n\n1. Uno\n2. Dos\n\n> Cita"

    assert speech_chunks(markdown) == [
        "Título",
        "Primero",
        "Segundo",
        "Uno",
        "Dos",
        "Cita",
    ]


def test_raw_html_is_dropped() -> None:
    markdown = "Texto <b>importante</b>.\n\n<details>\n\nDentro\n\n</details>"

    assert speech_chunks(markdown) == ["Texto importante.", "Dentro"]


def test_rules_and_empty_paragraphs_say_nothing() -> None:
    assert speech_chunks("Uno\n\n---\n\nDos") == ["Uno", "Dos"]


def test_long_paragraphs_are_cut_between_sentences() -> None:
    paragraph = " ".join(
        f"Frase {i} con algo de texto para alargarla." for i in range(40)
    )

    chunks = split_sentences(paragraph)

    assert len(chunks) > 1
    assert all(len(chunk) <= MAX_CHUNK_CHARS for chunk in chunks)
    assert " ".join(chunks) == paragraph


@pytest.mark.parametrize("paragraph", ["Corta.", "x" * (MAX_CHUNK_CHARS + 50)])
def test_short_paragraphs_and_single_long_sentences_stay_whole(paragraph: str) -> None:
    assert split_sentences(paragraph) == [paragraph]
