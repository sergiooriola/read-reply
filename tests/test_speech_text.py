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


@pytest.mark.parametrize(
    ("markdown", "spoken"),
    [
        ("<https://españa.es/ayuda>", "españa.es"),
        ("[el informe](file:///tmp/informe.html)", "el informe"),
        ("[javascript:x](javascript:x)", "javascript:x"),
    ],
    ids=["non-ascii-site", "local-file", "any-scheme"],
)
def test_links_are_read_as_written(markdown: str, spoken: str) -> None:
    assert speech_chunks(markdown) == [spoken]


def test_deep_nesting_loses_no_text() -> None:
    levels = 25
    markdown = "\n".join("  " * i + f"- Nivel {i}" for i in range(levels))

    assert speech_chunks(markdown + "\n\nFin.") == [
        *(f"Nivel {i}" for i in range(levels)),
        "Fin.",
    ]


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


@pytest.mark.parametrize(
    ("markdown", "spoken"),
    [
        ("- [x] Hecho\n- [ ] Pendiente", ["Hecho", "Pendiente"]),
        ("Texto[^1].\n\n[^1]: La nota.", ["Texto."]),
        ("Texto[^1].\n\n[^1]: Nota.\n    > [^2]: Otra.", ["Texto."]),
        ("Mira ![un gráfico](a.png).", ["Mira un gráfico."]),
        ("Mira ![I&amp;D](a.png).", ["Mira I&D."]),
        ("> [!WARNING]\n> Ojo.", ["Advertencia", "Ojo."]),
    ],
    ids=["task-list", "footnote", "nested-footnote", "image", "image-entity", "alert"],
)
def test_github_extensions_are_read_without_their_marks(
    markdown: str, spoken: list[str]
) -> None:
    assert speech_chunks(markdown) == spoken


def test_dollar_signs_are_prices_not_formulas() -> None:
    markdown = "Llevas 0,99 $ de 5 $; el plan cuesta 30 $/mes o 288 $/año."

    assert speech_chunks(markdown) == [markdown]


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
