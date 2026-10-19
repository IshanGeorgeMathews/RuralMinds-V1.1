"""Exam revision in a real week: 8A and 8B share the English Class 8 book, 8C has the
Malayalam book, 9A the Class 9 book. One teacher, two exams on different dates."""

import asyncio
import json

import pytest

from ruralminds import cache, exams
from ruralminds.db import connect, init_schema
from ruralminds.exams import ExamError, PortionIn

EN8, ML8, EN9 = 1, 2, 3
A8, B8, C8, A9 = 1, 2, 3, 4
CITED = {"text": "Bhimbetka is in Madhya Pradesh [S1].", "citations": [{"page_start": 11}]}


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "exams.db")
    init_schema(connection)
    connection.executescript(
        "INSERT INTO classes (id, grade, section, medium) VALUES"
        " (1, 8, 'A', 'en'), (2, 8, 'B', 'en'), (3, 8, 'C', 'ml'), (4, 9, 'A', 'en');"
        "INSERT INTO documents (id, book_id, title, board, medium, grade, subject, file_path,"
        " sha256, page_count) VALUES"
        " (1, 'ss8-en', 'SS 8', 'SCERT-KL', 'en', 8, 'social_science', 'p', 'sha-en8', 1),"
        " (2, 'ss8-ml', 'SS 8 ML', 'SCERT-KL', 'ml', 8, 'social_science', 'p', 'sha-ml8', 1),"
        " (3, 'ss9-en', 'SS 9', 'SCERT-KL', 'en', 9, 'social_science', 'p', 'sha-en9', 1);"
        "INSERT INTO class_books VALUES (1, 1), (2, 1), (3, 2), (4, 3);"
        "INSERT INTO users (id, username, role, pw_hash) VALUES (1, 'lakshmi', 'teacher', 'x');"
        "INSERT INTO book_chapters VALUES (1, 1, 'One', 7, 7), (1, 2, 'Two', 20, 20),"
        " (1, 3, 'Three', 40, 40), (1, 4, 'Four', 57, 57), (1, 5, 'Five', 75, 75);"
    )
    return connection


def portion(**changes) -> PortionIn:
    base = {
        "title": "Term exam",
        "document_id": EN8,
        "chapters": [1, 2, 3, 4],
        "class_ids": [A8, B8],
        "visible_from": "2026-10-20",
        "exam_on": "2026-10-30",
    }
    return PortionIn(**(base | changes))


def approved_question(conn, chapter: int = 2, text: str = "Where is Bhimbetka?") -> int:
    question_id = exams.add_question(conn, EN8, chapter, text, user_id=None)
    conn.execute(
        "UPDATE revision_questions SET status = 'draft', answer_json = ? WHERE id = ?",
        (json.dumps(CITED), question_id),
    )
    exams.approve(conn, question_id, user_id=None)
    return question_id


def test_portion_refuses_a_class_that_does_not_have_the_book(conn) -> None:
    mine = [A8, B8, C8, A9]
    exams.check_portion(conn, portion(), mine)
    with pytest.raises(ExamError, match="exam.class_without_book"):
        exams.check_portion(conn, portion(class_ids=[A8, C8]), mine)  # 8C: Malayalam book
    with pytest.raises(ExamError, match="exam.bad_classes"):
        exams.check_portion(conn, portion(), [A8])  # 8B is not this teacher's class
    with pytest.raises(ExamError, match="exam.bad_chapters"):
        exams.check_portion(conn, portion(chapters=[9]), mine)
    with pytest.raises(ExamError, match="exam.bad_dates"):
        exams.check_portion(conn, portion(visible_from="2026-11-01"), mine)


def test_one_bank_serves_both_classes_and_both_exams(conn) -> None:
    exams.save_portion(conn, portion(class_ids=[A8]), user_id=1)
    exams.save_portion(
        conn, portion(class_ids=[B8], chapters=[1, 2, 3, 4, 5], exam_on="2026-11-02"), 1
    )
    question_id = approved_question(conn)
    for class_id in (A8, B8):
        active = exams.student_revision(conn, class_id, "2026-10-25")
        assert [q["id"] for q in active[0]["questions"]] == [question_id]
        assert "answer" not in active[0]["questions"][0]  # attempt first: no answer in the list
    assert exams.student_revision(conn, C8, "2026-10-25") == []  # other book, other bank


def test_chips_follow_the_exam_dates(conn) -> None:
    exams.save_portion(conn, portion(), user_id=1)
    question_id = approved_question(conn)
    assert exams.student_revision(conn, A8, "2026-10-19") == []  # not visible yet
    assert exams.student_answer(conn, A8, question_id, "2026-10-30") is not None  # exam day
    assert exams.student_revision(conn, A8, "2026-10-31") == []  # the day after: gone
    assert exams.student_answer(conn, A8, question_id, "2026-10-31") is None


def test_tap_serves_the_answer_once_logged_per_class_only(conn) -> None:
    exams.save_portion(conn, portion(), user_id=1)
    question_id = approved_question(conn)
    answer = exams.student_answer(conn, A8, question_id, "2026-10-25")
    assert answer["text"] == CITED["text"] and answer["label"] == "teacher_approved"
    logged = conn.execute("SELECT class_id, outcome FROM answer_log").fetchall()
    assert [tuple(row) for row in logged] == [(A8, "cached")]
    assert exams.student_answer(conn, A9, question_id, "2026-10-25") is None  # not 9A's exam


def test_a_replaced_book_hides_answers_checked_against_the_old_one(conn) -> None:
    exams.save_portion(conn, portion(), user_id=1)
    question_id = approved_question(conn)
    conn.execute("UPDATE documents SET sha256 = 'sha-en8-v2' WHERE id = ?", (EN8,))
    assert exams.student_revision(conn, A8, "2026-10-25")[0]["questions"] == []
    assert exams.student_answer(conn, A8, question_id, "2026-10-25") is None


def test_approved_cited_answer_also_answers_the_typed_question(conn) -> None:
    approved_question(conn)
    assert cache.lookup(conn, "where is bhimbetka", "en", EN8, 2)["text"] == CITED["text"]


def test_edit_keeps_citations_and_reject_withdraws_the_cached_copy(conn) -> None:
    question_id = approved_question(conn)
    exams.approve(conn, question_id, user_id=1, edited_text="It is in Madhya Pradesh.")
    row = exams.question_row(conn, question_id)
    assert row["answer_kind"] == "edited"
    assert json.loads(row["answer_json"])["citations"] == CITED["citations"]
    exams.reject(conn, question_id)
    assert cache.lookup(conn, "Where is Bhimbetka?", "en", EN8, 2) is None


def test_teacher_written_answer_is_labelled_and_kept_out_of_the_typed_cache(conn) -> None:
    exams.save_portion(conn, portion(), user_id=1)
    question_id = exams.add_question(
        conn, EN8, 3, "Name two Harappan sites", user_id=1, written_answer="Harappa, Lothal."
    )
    assert exams.question_row(conn, question_id)["status"] == "approved"
    assert exams.student_answer(conn, A8, question_id, "2026-10-25")["label"] == "teacher_written"
    assert cache.lookup(conn, "Name two Harappan sites", "en", EN8, 3) is None


def test_the_same_question_twice_in_a_chapter_is_refused(conn) -> None:
    exams.add_question(conn, EN8, 2, "Where is Bhimbetka?", user_id=1)
    with pytest.raises(ExamError, match="exam.duplicate_question"):
        exams.add_question(conn, EN8, 2, "where is bhimbetka", user_id=1)


@pytest.mark.parametrize(
    ("final", "status"),
    [
        ({"event": "done", "data": {"text": "x [S1]", "citations": [{"page_start": 1}]}}, "draft"),
        ({"event": "refused", "data": {"reason": "not_in_textbook"}}, "not_in_book"),
        ({"event": "busy", "data": {"message_key": "error.busy"}}, "failed"),
    ],
)
def test_pipeline_result_becomes_a_draft_a_not_in_book_or_a_retry(conn, monkeypatch, final, status):
    async def fake_stream(conn, client, queue, request):
        assert request.mode == "explain" and not request.use_cache and request.class_id == 0
        yield {"event": "queued", "data": {"position": 1}}
        yield final

    monkeypatch.setattr(exams, "answer_stream", fake_stream)
    question_id = exams.add_question(conn, EN8, 2, "Key points of chapter two", user_id=1)
    assert asyncio.run(exams.answer_question(conn, None, None, question_id)) == status
    assert exams.question_row(conn, question_id)["status"] == status


def test_teacher_can_answer_what_the_book_does_not(conn, monkeypatch) -> None:
    question_id = exams.add_question(conn, EN8, 2, "Why did Ashoka give up war?", user_id=1)
    conn.execute(
        "UPDATE revision_questions SET status = 'not_in_book', answer_json = ? WHERE id = ?",
        (json.dumps({"reason": "not_in_textbook"}), question_id),
    )
    with pytest.raises(ExamError, match="exam.no_answer_yet"):
        exams.approve(conn, question_id, user_id=1)  # nothing to approve without her text
    exams.approve(conn, question_id, user_id=1, edited_text="After the Kalinga war...")
    row = exams.question_row(conn, question_id)
    assert row["status"] == "approved" and row["answer_kind"] == "written"
    assert json.loads(row["answer_json"]) == {"text": "After the Kalinga war...", "citations": []}
