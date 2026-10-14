from pathlib import Path

import pytest

from ruralminds.chunker import PageInput, chunk_pages, split_sentences
from ruralminds.db import connect, init_schema, serialize_vector
from ruralminds.ingest import Book, Chapter, load_books
from ruralminds.pages import clean_text, drop_running_titles, needs_ocr, script_ratio

ML_TEXT = "മധ്യപ്രദേശിലെ ഭിംബേഡ്ക ഇന്ത്യയിലെ പ്രാചീന ശിലായുഗ കേന്ദ്രങ്ങളിൽ ശ്രദ്ധേയമാണ്."
LEGACY_FONT_TEXT = "ASn-ÿm-\\-imkv{Xw VIII 11 tImisØ Is≠Øp∂p efn-X-amb Hcp ssat{Im-kvtIm-∏ns‚"


# ---------- page classification ----------
def test_legacy_font_malayalam_goes_to_ocr() -> None:
    assert needs_ocr(LEGACY_FONT_TEXT, "ml", 0.6)


def test_unicode_malayalam_uses_text_layer() -> None:
    assert not needs_ocr(ML_TEXT * 2, "ml", 0.6)
    assert script_ratio(ML_TEXT, "ml") > 0.95


def test_clean_english_uses_text_layer() -> None:
    text = "Bhimbetka in Madhya Pradesh is a notable Palaeolithic site in India."
    assert not needs_ocr(text, "en", 0.6)


def test_symbol_soup_english_goes_to_ocr() -> None:
    assert needs_ocr("#\t'\t+\t%\t'\t+\t'2\t$'\t3\t+\t'\t2\t$#3 . ' " * 3, "en", 0.6)


def test_clean_text_drops_rule_lines_and_page_numbers() -> None:
    raw = "1234567890123456789012345\r\nEarly humans\r\n11\r\nlived in  caves￾"
    assert clean_text(raw) == "Early humans\nlived in caves"


# ---------- chunking ----------
def _page(printed: int, chapter: int, text: str) -> PageInput:
    return PageInput(printed, chapter, f"Chapter {chapter}", text)


def test_chunks_track_page_span_and_size() -> None:
    sentence = "Early humans made tools from stone and lived near rivers. "
    pages = [_page(11, 1, sentence * 10), _page(12, 1, sentence * 10)]
    chunks = chunk_pages(pages, target=300, max_chars=500)
    assert all(len(c.text) <= 300 + len(sentence) for c in chunks)
    assert chunks[0].page_start == 11
    assert chunks[-1].page_end == 12
    assert any(c.page_start == 11 and c.page_end == 12 for c in chunks)


def test_chunks_never_cross_chapters() -> None:
    pages = [_page(21, 1, "End of chapter one. " * 5), _page(23, 2, "Start of chapter two. " * 5)]
    chunks = chunk_pages(pages, target=1000, max_chars=1600)
    assert [c.chapter_no for c in chunks] == [1, 2]


def test_no_empty_chunks_and_tiny_tail_is_merged() -> None:
    pages = [
        _page(7, 1, "A long sentence about early human life in caves. " * 6 + "Short."),
        _page(8, 1, ""),
    ]
    chunks = chunk_pages(pages, target=200, max_chars=400)
    assert all(c.text.strip() for c in chunks)
    assert chunks[-1].text.endswith("Short.")
    assert len(chunks[-1].text) > len("Short.")


def test_long_runs_without_full_stops_are_split() -> None:
    parts = split_sentences("word " * 500, max_chars=200)
    assert all(len(p) <= 200 for p in parts)


# ---------- database ----------
@pytest.fixture
def conn():
    connection = connect(":memory:")
    init_schema(connection)
    yield connection
    connection.close()


def test_fts_keeps_malayalam_words_whole(conn) -> None:
    conn.execute(
        "INSERT INTO documents (id, book_id, title, board, medium, grade, subject,"
        " file_path, sha256, page_count) VALUES (1,'b','t','SCERT-KL','ml',8,'ss','p','s',1)"
    )
    conn.execute(
        "INSERT INTO chunks (document_id, ordinal, chapter_no, chapter_title, page_start,"
        " page_end, text) VALUES (1, 0, 1, 'c', 11, 11, ?)",
        (ML_TEXT,),
    )
    match = "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ?"
    assert conn.execute(match, ('"ഭിംബേഡ്ക"',)).fetchall()
    # With the default tokenizer a single consonant matched; it must not any more.
    assert not conn.execute(match, ('"ബ"',)).fetchall()


def test_vector_search_respects_medium_filter(conn) -> None:
    for chunk_id, medium in [(1, "en"), (2, "ml")]:
        vector = [1.0] + [0.0] * 1023
        conn.execute(
            "INSERT INTO chunk_vectors VALUES (?,?,?,?,?,?)",
            (chunk_id, serialize_vector(vector), medium, "social_science", 1, 1),
        )
    rows = conn.execute(
        "SELECT chunk_id FROM chunk_vectors WHERE embedding MATCH ? AND k = 5 AND medium = 'ml'",
        (serialize_vector([1.0] + [0.0] * 1023),),
    ).fetchall()
    assert [r[0] for r in rows] == [2]


# ---------- book manifest ----------
def test_chapter_mapping() -> None:
    book = Book(
        "b",
        "t",
        "SCERT-KL",
        "en",
        8,
        "ss",
        Path("x.pdf"),
        "",
        "eng",
        0,
        120,
        [Chapter(1, "One", 7), Chapter(2, "Two", 23)],
    )
    assert book.chapter_for(6) is None
    assert book.chapter_for(7).no == 1
    assert book.chapter_for(22).no == 1
    assert book.chapter_for(23).no == 2
    assert book.chapter_for(121) is None


def test_manifest_loads() -> None:
    books = load_books(Path(__file__).parents[1] / "books.toml")
    assert {"ss8-pt1-en", "ss8-pt1-ml"} <= set(books)
    assert [c.start for c in books["ss8-pt1-en"].chapters] == [7, 23, 41, 57, 75, 87, 107]


# ---------- running headers ----------
def test_running_headers_and_ocr_fragments_are_dropped() -> None:
    raw = "\n".join(  # noqa: FLY002 - one header per line reads better than one long string
        [
            "1 0",
            "Social Science",
            "Standard VIII",
            "സ്റ്റാൻഡേർഡ് Vill",
            "സാമഃഹ്ൃശാസ്(ത്രം",  # OCR misread of the Social Science header
            "12 EARLY HUMAN LIFE",
            "Ws",
            "7777777777",
            "Early humans lived in caves.",
        ]
    )
    assert clean_text(raw) == "Early humans lived in caves."


def test_running_chapter_title_dropped_even_with_ocr_errors() -> None:
    titles = ["ഭൂപടങ്ങൾ വായിക്കാം", "Early Human Life"]
    text = "ഭൂചടങ്ങൾ വായിക്കാം 97\nഭൂപടത്തിലെ ദിശകൾ കണ്ടെത്താം.\nEarly human life was hard."
    assert drop_running_titles(text, titles) == (
        "ഭൂപടത്തിലെ ദിശകൾ കണ്ടെത്താം.\nEarly human life was hard."
    )
