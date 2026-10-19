from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ruralminds import auth
from ruralminds.config import settings
from ruralminds.controls import Controls, save_controls
from ruralminds.db import connect, init_schema
from ruralminds.main import app

PASSWORD = "kite42"


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", tmp_path / "test.db")
    monkeypatch.setattr(settings, "books_file", tmp_path / "none.toml")
    for name in ("books_dir", "uploads_dir", "ocr_cache_dir", "page_cache_dir"):
        monkeypatch.setattr(settings, name, tmp_path / name)
    conn = connect(settings.db_path)
    init_schema(conn)
    pw_hash = auth.hash_password(PASSWORD)
    conn.executescript(
        "INSERT INTO classes (id, grade, section, medium) VALUES (1, 8, 'A', 'en'), (2, 8, 'B', 'ml');"
        "INSERT INTO documents (id, book_id, title, board, medium, grade, subject, file_path,"
        " sha256, page_count, status) VALUES"
        " (1, 'pub', 'Social Science', 'SCERT-KL', 'en', 8, 'social_science', 'p', 'a', 1, 'published'),"
        " (2, 'draft', 'Science', 'SCERT-KL', 'en', 8, 'science', 'p', 'b', 1, 'ready'),"
        " (3, 'other', 'Malayalam book', 'SCERT-KL', 'ml', 8, 'social_science', 'p', 'c', 1, 'published');"
        "INSERT INTO class_books VALUES (1, 1), (1, 2), (2, 3);"
        "INSERT INTO book_chapters VALUES (1, 1, 'Early Human Life', 7, 7);"
    )
    conn.executemany(
        "INSERT INTO users (username, role, class_id, pw_hash) VALUES (?,?,?,?)",
        [
            ("8a-01", "student", 1, pw_hash),
            ("teacher", "teacher", None, pw_hash),
            ("admin", "admin", None, pw_hash),
        ],
    )
    conn.commit()
    conn.close()
    with TestClient(app) as test_client:
        yield test_client


def login(client: TestClient, username: str) -> None:
    response = client.post("/api/login", json={"username": username, "password": PASSWORD})
    assert response.status_code == 200, response.text


def test_wrong_password_and_throttle(client) -> None:
    for _ in range(settings.login_max_failures):
        response = client.post("/api/login", json={"username": "8a-01", "password": "nope"})
        assert response.status_code == 401
    response = client.post("/api/login", json={"username": "8a-01", "password": PASSWORD})
    assert response.status_code == 429


def test_student_sees_only_published_books_of_their_class(client) -> None:
    login(client, "8a-01")
    me = client.get("/api/me").json()
    assert me["role"] == "student" and me["class"]["section"] == "A"
    books = client.get("/api/catalog").json()["books"]
    assert [book["id"] for book in books] == [1]
    assert books[0]["chapters"][0]["title"] == "Early Human Life"


def test_student_cannot_ask_other_books_or_use_teacher_routes(client) -> None:
    login(client, "8a-01")
    for document_id in (2, 3):  # unpublished; another class's book
        response = client.post("/api/ask", json={"question": "x", "document_id": document_id})
        assert response.status_code == 403
    assert client.get("/api/teacher/overview").status_code == 403
    assert client.get("/api/admin/overview").status_code == 403


def test_signed_out_requests_are_refused(client) -> None:
    assert client.get("/api/catalog").status_code == 401
    assert client.get("/api/teacher/overview").status_code == 401


def test_admin_only_from_the_server_machine(client, monkeypatch) -> None:
    response = client.post("/api/login", json={"username": "admin", "password": PASSWORD})
    assert response.status_code == 403  # the test client is not 127.0.0.1
    monkeypatch.setattr(auth, "is_local", lambda request: True)
    login(client, "admin")
    response = client.post("/api/admin/users/bulk", json={"class_id": 1, "count": 3})
    names = [account["username"] for account in response.json()["accounts"]]
    assert names == ["8a-02", "8a-03", "8a-04"]  # 8a-01 already exists


def test_paused_answering_is_enforced_by_the_server(client) -> None:
    conn = connect(settings.db_path)
    save_controls(conn, Controls(answering_enabled=False))
    conn.close()
    login(client, "8a-01")
    response = client.post("/api/ask", json={"question": "Where is Bhimbetka?", "document_id": 1})
    assert "event: blocked" in response.text and "error.paused" in response.text


def test_teacher_sees_all_books_and_can_publish(client) -> None:
    login(client, "teacher")
    overview = client.get("/api/teacher/overview").json()
    assert {book["id"] for book in overview["books"]} == {1, 2, 3}
    response = client.post("/api/teacher/books/2/publish", json={"published": True})
    assert response.json()["status"] == "published"


def test_form_posts_are_rejected(client) -> None:
    response = client.post(
        "/api/login",
        content="username=8a-01&password=kite42",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 415


def test_android_connectivity_check(client) -> None:
    assert client.get("/generate_204").status_code == 204


def test_one_question_in_flight_per_phone_with_a_backstop(monkeypatch) -> None:
    from ruralminds import api_common

    asking: dict[str, float] = {}
    assert api_common._start_asking(asking, "phone-a")
    assert not api_common._start_asking(asking, "phone-a")  # second question while waiting
    assert api_common._start_asking(asking, "phone-b")  # other phones are unaffected
    asking["phone-a"] -= api_common.settings.one_question_ttl_s + 1  # cleanup never ran
    assert api_common._start_asking(asking, "phone-a")


def test_closing_the_response_frees_the_phone_and_closes_the_answer() -> None:
    import asyncio

    from ruralminds import api_common

    closed = []

    async def answer():
        try:
            yield {"event": "queued", "data": {"position": 1}}
            yield {"event": "token", "data": {"text": "never sent"}}
        finally:
            closed.append(True)

    async def scenario() -> dict[str, float]:
        asking = {"phone-a": 0.0}
        events = api_common._closing(answer(), asking, "phone-a")
        await events.__anext__()
        await events.aclose()  # the phone went away mid-wait
        return asking

    assert asyncio.run(scenario()) == {} and closed == [True]


def test_teacher_exam_to_student_chip_end_to_end(client) -> None:
    from datetime import date, timedelta

    conn = connect(settings.db_path)
    conn.execute(
        "INSERT INTO teacher_classes VALUES ((SELECT id FROM users WHERE username = 'teacher'), 1)"
    )
    conn.commit()
    conn.close()
    today = date.today()
    login(client, "teacher")
    exam = {
        "title": "Term exam",
        "document_id": 1,
        "chapters": [1],
        "class_ids": [1],
        "visible_from": today.isoformat(),
        "exam_on": (today + timedelta(days=5)).isoformat(),
    }
    assert client.post("/api/teacher/exams", json=exam | {"class_ids": [2]}).status_code == 400
    assert client.post("/api/teacher/exams", json=exam).status_code == 200
    question = {
        "document_id": 1,
        "chapter_no": 1,
        "question": "Name a rock shelter site.",
        "answer": "Bhimbetka.",
    }
    question_id = client.post("/api/teacher/revision", json=question).json()["id"]
    listing = client.get("/api/teacher/exams").json()
    assert listing["today"] == today.isoformat()
    assert listing["portions"][0]["progress"] == {"approved": 1}
    client.post("/api/logout")

    login(client, "8a-01")
    active = client.get("/api/revision").json()
    assert active[0]["questions"] == [
        {"id": question_id, "chapter_no": 1, "question": "Name a rock shelter site."}
    ]
    answer = client.post(f"/api/revision/{question_id}/answer").json()
    assert answer["text"] == "Bhimbetka." and answer["label"] == "teacher_written"
    assert client.post("/api/revision/999/answer").status_code == 404


def test_teacher_cannot_touch_another_teachers_book_bank(client) -> None:
    login(client, "teacher")  # no classes allocated in this fixture
    question = {"document_id": 1, "chapter_no": 1, "question": "Anything?", "answer": "x"}
    assert client.post("/api/teacher/revision", json=question).status_code == 403
    assert client.get("/api/teacher/revision/1/1").status_code == 403
