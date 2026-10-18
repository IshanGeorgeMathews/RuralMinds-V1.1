"""Review verdicts reach the item files, and the eval skips what a reviewer rejected."""

from pathlib import Path

from eval.apply_review import apply, read_verdicts
from eval.run import select_items


def test_read_verdicts_takes_first_letter_and_skips_blank_rows(tmp_path: Path) -> None:
    sheet = tmp_path / "review.csv"
    sheet.write_text(
        "id,verdict,note,question\n"
        "a,OK,,q1\n"
        "b,fix,wrong page: 27 not 26,q2\n"
        "c,,,q3\n"
        "d,Drop,ambiguous,q4\n",
        encoding="utf-8-sig",
    )
    assert read_verdicts(sheet) == {
        "a": ("o", ""),
        "b": ("f", "wrong page: 27 not 26"),
        "d": ("d", "ambiguous"),
    }


def test_apply_marks_verified_dropped_and_lists_fixes() -> None:
    items = [{"id": i, "verified": False} for i in "abcd"]
    fixes = apply(items, {"a": ("o", ""), "b": ("f", "wrong page"), "d": ("d", "")})
    assert [item["verified"] for item in items] == [True, False, False, False]
    assert items[3]["status"] == "dropped"
    assert fixes == ["b: wrong page"]


def test_select_items_skips_dropped_and_unverified_on_request() -> None:
    items = [
        {"id": "a", "verified": True, "split": "dev"},
        {"id": "b", "verified": False, "split": "dev"},
        {"id": "c", "verified": True, "status": "dropped", "split": "dev"},
        {"id": "d", "verified": True, "split": "test"},
    ]
    assert [i["id"] for i in select_items(items, None, False)] == ["a", "b", "d"]
    assert [i["id"] for i in select_items(items, "dev", True)] == ["a"]


def test_review_sheet_shows_indexed_text_of_gold_pages() -> None:
    from eval.review_sheet import NO_TEXT, indexed_text
    from ruralminds.db import connect, init_schema

    conn = connect(":memory:")
    init_schema(conn)
    conn.execute(
        "INSERT INTO documents (id, book_id, title, board, medium, grade, subject, file_path,"
        " sha256, page_count) VALUES (1, 'b', 't', 'SCERT-KL', 'en', 8, 'science', 'p', 's', 1)"
    )
    for ordinal, (start, end, text) in enumerate(
        [
            (125, 126, "velocity changes"),
            (126, 126, "a = change in velocity / time"),
            (128, 128, "x"),
        ]
    ):
        conn.execute(
            "INSERT INTO chunks (document_id, ordinal, chapter_no, chapter_title, page_start,"
            " page_end, text) VALUES (1, ?, 9, 'Motion', ?, ?, ?)",
            (ordinal, start, end, text),
        )
    shown = indexed_text(conn, "b", [126])
    assert "[p125-126] velocity changes" in shown and "a = change in velocity / time" in shown
    assert "[p128" not in shown
    assert indexed_text(conn, "b", [140]) == NO_TEXT


def test_split_keeps_parallel_items_together_and_forces_tuned_facts_to_dev() -> None:
    from eval.split import assign

    english = [
        {"id": f"ss-en-{n:03d}", "style": "lookup", "expected": "answer"} for n in range(1, 21)
    ]
    malayalam = [
        {"id": f"ss-ml-{n:03d}", "parallel_of": f"ss-en-{n:03d}", "style": "lookup"}
        for n in range(1, 21)
    ]
    split = assign({"en": english, "ml": malayalam})
    assert set(split) == {f"ss-en-{n:03d}" for n in range(1, 21)}  # one group per parallel set
    assert split["ss-en-001"] == "dev"  # tuned on in v1
    assert sum(value == "dev" for value in split.values()) == 6  # 30% of 20
    assert assign({"en": english, "ml": malayalam}) == split  # deterministic


def test_fingerprint_changes_when_a_test_item_changes() -> None:
    from eval.split import fingerprint

    items = [
        {"id": "a", "question": "q", "split": "test"},
        {"id": "b", "question": "x", "split": "dev"},
    ]
    before = fingerprint(items)
    items[1]["question"] = "dev items may change"
    assert fingerprint(items) == before
    items[0]["question"] = "q2"
    assert fingerprint(items) != before
