import pytest

from ruralminds.db import connect, init_schema, serialize_vector
from ruralminds.retrieve import Filters, fts_query, fuse, search
from ruralminds.textnorm import malayalam_stem, normalize

DIM = 1024


# ---------- normalisation ----------
def test_old_and_atomic_chillu_normalise_to_the_same_word() -> None:
    ocr_form = "പാര്‍ലമെന്റ്"  # Tesseract
    keyboard_form = "പാർലമെന്റ്"  # Gboard
    assert ocr_form != keyboard_form
    assert normalize(ocr_form) == normalize(keyboard_form) == keyboard_form


def test_zwnj_is_dropped() -> None:
    assert normalize("ഡ്‌") == "ഡ്"


def test_malayalam_stem_strips_case_endings() -> None:
    assert malayalam_stem("ഭിംബേഡ്കയുടെ") == "ഭിംബേഡ്ക"
    assert malayalam_stem("ചുമതലകൾ") == "ചുമതല"
    assert malayalam_stem("സംസ്കാരത്തിന്റെ") == "സംസ്കാര"
    assert malayalam_stem("ഇൽ") == "ഇൽ"  # too short to strip


# ---------- keyword query ----------
def test_fts_query_quotes_terms_and_drops_stopwords() -> None:
    assert fts_query("Why is Bhimbetka important?") == '"bhimbetka"* OR "important"*'


def test_fts_query_neutralises_fts_syntax() -> None:
    query = fts_query('rivers" OR NEAR(x) AND *')
    assert query is not None and '""' not in query and "NEAR(" not in query


def test_fts_query_malayalam_uses_stems() -> None:
    assert fts_query("ഭിംബേഡ്കയുടെ പ്രത്യേകത എന്താണ്?") == '"ഭിംബേഡ്ക"* OR "പ്രത്യേകത"*'


def test_fts_query_only_stopwords_returns_none() -> None:
    assert fts_query("what is the?") is None


# ---------- fusion ----------
def test_rrf_rewards_agreement_between_searches() -> None:
    fused = fuse(keyword=[1, 2, 3], vector=[(3, 0.2), (4, 0.3)])
    ranked = sorted(fused.values(), key=lambda hit: hit.score, reverse=True)
    assert ranked[0].chunk_id == 3  # in both lists beats rank 1 in only one
    assert fused[3].fts_rank == 3 and fused[3].vec_rank == 1
    assert fused[3].similarity == pytest.approx(0.8)
    assert fused[1].similarity is None


# ---------- search with filters ----------
def _unit(index: int) -> list[float]:
    vector = [0.0] * DIM
    vector[index] = 1.0
    return vector


@pytest.fixture
def conn():
    connection = connect(":memory:")
    init_schema(connection)
    rows = [  # (doc, medium, chapter, page, text, vector axis)
        (1, "en", 1, 11, "Bhimbetka rock shelters in Madhya Pradesh", 0),
        (1, "en", 4, 62, "The Parliament makes laws for the country", 1),
        (2, "ml", 1, 11, "ഭിംബേഡ്ക ശിലാഗൃഹങ്ങൾ", 0),
        (3, "en", 1, 5, "Bhimbetka in a second English book", 0),
    ]
    for doc_id, medium in [(1, "en"), (2, "ml"), (3, "en")]:
        connection.execute(
            "INSERT INTO documents (id, book_id, title, board, medium, grade, subject, file_path,"
            " sha256, page_count) VALUES (?,?,'t','SCERT-KL',?,8,'social_science','p','s',1)",
            (doc_id, f"book-{doc_id}", medium),
        )
    for ordinal, (doc_id, medium, chapter, page, text, axis) in enumerate(rows):
        cursor = connection.execute(
            "INSERT INTO chunks (document_id, ordinal, chapter_no, chapter_title, page_start,"
            " page_end, text, token_count) VALUES (?,?,?,'c',?,?,?,10)",
            (doc_id, ordinal, chapter, page, page, text),
        )
        connection.execute(
            "INSERT INTO chunk_vectors VALUES (?,?,?,?,?,?)",
            (cursor.lastrowid, serialize_vector(_unit(axis)), medium, "social_science", chapter,
             doc_id),
        )
    yield connection
    connection.close()


def test_search_finds_page_and_respects_medium(conn) -> None:
    hits = search(conn, "Bhimbetka", _unit(0), Filters("en", "social_science"), top_k=3)
    assert hits[0].page_start == 11 and hits[0].medium == "en"
    assert all(hit.medium == "en" for hit in hits)


def test_search_respects_chapter_filter(conn) -> None:
    hits = search(conn, "Bhimbetka", _unit(0), Filters("en", "social_science", 4), top_k=3)
    assert [hit.chapter_no for hit in hits] == [4]


def test_search_other_subject_returns_nothing(conn) -> None:
    assert search(conn, "Bhimbetka", _unit(0), Filters("en", "maths"), top_k=3) == []


def test_search_stays_inside_one_book(conn) -> None:
    both = search(conn, "Bhimbetka", _unit(0), Filters("en", "social_science"), top_k=5)
    assert {hit.book_id for hit in both} == {"book-1", "book-3"}
    one = search(conn, "Bhimbetka", _unit(0), Filters("en", "social_science", None, 3), top_k=5)
    assert [hit.book_id for hit in one] == ["book-3"]
