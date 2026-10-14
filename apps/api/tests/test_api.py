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
