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


# ---------- idle-time drafting worker (step 3) ----------
from types import SimpleNamespace

import httpx

from ruralminds import revision_worker
from ruralminds.answer import AnswerQueue
from ruralminds.controls import Controls, save_controls


def drafted(conn, chapter: int, text: str, status: str) -> None:
    question_id = exams.add_question(conn, EN8, chapter, text, None, source="drafted")
    conn.execute("UPDATE revision_questions SET status = ? WHERE id = ?", (status, question_id))


def test_shortfall_counts_usable_suggestions_and_caps_the_tries(conn) -> None:
    exams.save_portion(conn, portion(chapters=[1, 2], drafts_per_chapter=3), user_id=1)
    exams.save_portion(conn, portion(chapters=[2], drafts_per_chapter=5, exam_on="2026-11-02"), 1)
    drafted(conn, 1, "Q one?", "draft")
    drafted(conn, 1, "Q two?", "rejected")  # set aside: does not count as usable
    on = "2026-10-21"
    gaps = revision_worker.chapter_shortfalls(conn, on)
    assert [(g.document_id, g.chapter, g.missing) for g in gaps] == [(EN8, 1, 2), (EN8, 2, 5)]
    for n in range(7):  # 1 usable + 8 tried >= 3 wanted x 3 tries: stop drafting chapter 1
        drafted(conn, 1, f"Bad {n}?", "rejected")
    assert [(g.chapter, g.missing) for g in revision_worker.chapter_shortfalls(conn, on)] == [
        (2, 5)
    ]
    assert revision_worker.chapter_shortfalls(conn, "2026-11-03") == []  # both exams over


def test_teacher_questions_are_answered_before_suggestions(conn) -> None:
    drafted(conn, 1, "Suggested first?", "pending")
    own = exams.add_question(conn, EN8, 2, "My question?", user_id=1)
    assert revision_worker.next_pending(conn, set()).question_id == own
    assert revision_worker.next_pending(conn, {own}).question_id != own  # already being answered


def test_drafted_lines_are_cleaned() -> None:
    reply = (
        "Here are questions:\n1. Where is Bhimbetka?\n- Why did farming begin?\nNo mark\nQ3: ok?"
    )
    assert revision_worker.parse_questions(reply) == [
        "Where is Bhimbetka?",
        "Why did farming begin?",
    ]


def test_drafting_adds_new_questions_and_steps_aside_for_a_student(conn, monkeypatch) -> None:
    conn.execute(
        "INSERT INTO chunks (document_id, ordinal, chapter_no, chapter_title, page_start,"
        " page_end, text) VALUES (1, 1, 2, 'Two', 20, 20, 'Harappa had drains.')"
    )
    exams.add_question(conn, EN8, 2, "Did Harappa have drains?", user_id=1)

    async def fake_complete(messages, client, max_tokens):
        assert "Harappa had drains." in messages[1]["content"]
        return "Did Harappa have drains?\nWhy were drains built?\nWhere was Lothal?"

    monkeypatch.setattr(revision_worker, "complete", fake_complete)
    queue = AnswerQueue(slots=1, max_waiting=5)
    added = asyncio.run(revision_worker.draft_chapter(conn, None, queue, EN8, 2, missing=2))
    assert added == 2 and not queue.busy()  # the duplicate is skipped; the slot is given back
    holder = queue.join()  # a student is being answered
    assert asyncio.run(revision_worker.draft_chapter(conn, None, queue, EN8, 2, missing=1)) == 0
    assert queue.waiting == 0
    queue.leave(holder)


def test_worker_only_runs_when_no_student_needs_the_model(conn, monkeypatch) -> None:
    exams.save_portion(
        conn,
        portion(
            chapters=[1], drafts_per_chapter=1, visible_from="2020-01-01", exam_on="2099-01-01"
        ),
        user_id=1,
    )
    busy_slots = {"value": False}

    def slots(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"is_processing": busy_slots["value"]}])

    async def fake_draft(*args):
        return 1

    monkeypatch.setattr(revision_worker, "draft_chapter", fake_draft)

    async def scenario() -> list:
        async with httpx.AsyncClient(transport=httpx.MockTransport(slots)) as http:
            state = SimpleNamespace(
                db=conn, http=http, queue=AnswerQueue(1, 5), answering=set(), last_ask=0.0
            )
            worker = revision_worker.RevisionWorker(state)
            results = [await worker.step()]  # idle: drafts
            busy_slots["value"] = True
            results.append(await worker.step())  # a slot is generating
            busy_slots["value"] = False
            state.last_ask = __import__("time").monotonic()
            results.append(await worker.step())  # a student asked just now
            state.last_ask = 0.0
            save_controls(conn, Controls(answering_enabled=False))
            results.append(await worker.step())  # the admin paused the model
            return results

    assert asyncio.run(scenario()) == ["drafted", None, None, None]


def test_the_soonest_exam_gets_its_suggestions_first(conn) -> None:
    exams.save_portion(conn, portion(chapters=[1], exam_on="2026-11-10"), user_id=1)
    exams.save_portion(conn, portion(chapters=[4], exam_on="2026-10-22"), user_id=1)
    order = [g.chapter for g in revision_worker.chapter_shortfalls(conn, "2026-10-21")]
    assert order == [4, 1]
    late = exams.add_question(conn, EN8, 1, "Later exam question?", None, source="drafted")
    soon = exams.add_question(conn, EN8, 4, "Sooner exam question?", None, source="drafted")
    assert revision_worker.next_pending(conn, set()).question_id == soon != late


def test_a_sooner_exams_drafting_beats_answering_a_later_exams_questions() -> None:
    pending, gap = revision_worker.Pending, revision_worker.Shortfall
    later = pending(1, "drafted", "2026-10-27")
    today_gap = [gap(3, 1, 6, "2026-10-20")]
    assert not revision_worker.answer_first(later, today_gap)  # draft for today's exam first
    assert revision_worker.answer_first(pending(2, "teacher", "2026-10-27"), today_gap)
    assert revision_worker.answer_first(pending(1, "drafted", "2026-10-20"), today_gap)
    assert revision_worker.answer_first(later, [])
    assert not revision_worker.answer_first(None, today_gap)
