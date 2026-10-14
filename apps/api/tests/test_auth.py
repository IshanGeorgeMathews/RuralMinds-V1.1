import pytest

from ruralminds import auth, cache
from ruralminds.controls import Controls, ask_blocked, load_controls, save_controls
from ruralminds.db import connect, init_schema


@pytest.fixture
def conn():
    connection = connect(":memory:")
    init_schema(connection)
    connection.execute("INSERT INTO classes (id, grade, section, medium) VALUES (1, 8, 'A', 'en')")
    connection.execute(
        "INSERT INTO users (id, username, role, class_id, pw_hash) VALUES (1, '8a-01', 'student',"
        " 1, ?)",
        (auth.hash_password("kite42"),),
    )
    yield connection
    connection.close()


def test_password_hash_round_trip() -> None:
    stored = auth.hash_password("kite42")
    assert stored.startswith("scrypt$") and "kite42" not in stored
    assert auth.verify_password("kite42", stored)
    assert not auth.verify_password("kite43", stored)
    assert not auth.verify_password("kite42", "garbage")


def test_generated_passwords_avoid_lookalike_characters() -> None:
    password = auth.new_password(200)
    assert not set(password) & set("0O1lI")


def test_authenticate(conn) -> None:
    assert auth.authenticate(conn, "8A-01", "kite42").username == "8a-01"  # case-insensitive
    assert auth.authenticate(conn, "8a-01", "wrong") is None
    assert auth.authenticate(conn, "nobody", "kite42") is None
    conn.execute("UPDATE users SET enabled = 0")
    assert auth.authenticate(conn, "8a-01", "kite42") is None


def test_session_expires_when_idle(conn) -> None:
    user = auth.authenticate(conn, "8a-01", "kite42")
    token = auth.create_session(conn, user, now=1000.0)
    assert auth.session_user(conn, token, now=1000.0 + 60).id == 1
    idle = auth.idle_limit("student")
    assert auth.session_user(conn, token, now=1060.0 + idle + 1) is None
    assert conn.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0  # cleaned up


def test_disabling_an_account_ends_its_session(conn) -> None:
    token = auth.create_session(conn, auth.authenticate(conn, "8a-01", "kite42"))
    conn.execute("UPDATE users SET enabled = 0")
    assert auth.session_user(conn, token) is None


def test_login_throttle() -> None:
    throttle = auth.LoginThrottle(max_failures=3, window_seconds=600)
    for second in range(3):
        throttle.failed("8a-01", now=100.0 + second)
    assert throttle.blocked("8A-01", now=110.0)
    assert not throttle.blocked("8a-01", now=100.0 + 601 + 3)  # window has passed
    throttle.succeeded("8a-01")
    assert not throttle.blocked("8a-01", now=110.0)


def test_controls_round_trip_and_blocking(conn) -> None:
    assert load_controls(conn) == Controls()
    save_controls(
        conn, Controls(answering_enabled=True, allowed_languages=["en"], disabled_classes=[2])
    )
    controls = load_controls(conn)
    assert ask_blocked(controls, "ml", 1) == "error.language_off"
    assert ask_blocked(controls, "en", 2) == "error.class_off"
    assert ask_blocked(controls, "en", None) is None
    save_controls(conn, Controls(answering_enabled=False))
    assert ask_blocked(load_controls(conn), "en", 1) == "error.paused"
    with pytest.raises(ValueError):
        save_controls(conn, Controls(allowed_languages=["fr"]))


def _book(conn, sha: str = "a" * 64) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO documents (id, book_id, title, board, medium, grade, subject,"
        " file_path, sha256, page_count) VALUES (1, 'b', 't', 'SCERT-KL', 'en', 8,"
        " 'social_science', 'p', ?, 1)",
        (sha,),
    )


def test_cache_matches_exact_question_only(conn) -> None:
    _book(conn)
    answer = {"text": "Rock shelters [S1].", "citations": []}
    cache.approve(conn, "Where is Bhimbetka?", "en", 1, None, answer)
    assert cache.lookup(conn, "  where is BHIMBETKA ", "en", 1, None) == answer
    assert cache.lookup(conn, "Where is Bhimbetka?", "ml", 1, None) is None
    assert cache.lookup(conn, "Where is Bhimbetka?", "en", 1, 2) is None
    assert cache.lookup(conn, "Why is Bhimbetka important?", "en", 1, None) is None


def test_cache_ignores_answers_for_an_older_book(conn) -> None:
    _book(conn)
    cache.approve(conn, "Where is Bhimbetka?", "en", 1, None, {"text": "x", "citations": []})
    _book(conn, sha="b" * 64)  # the teacher replaced the PDF
    assert cache.lookup(conn, "Where is Bhimbetka?", "en", 1, None) is None


def test_no_table_links_questions_to_accounts(conn) -> None:
    """Rule 4: question records carry a class at most, never a user, session or device."""
    for table in ("answer_log", "unanswered", "answer_cache"):
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        assert not columns & {"user_id", "student_id", "username", "session", "device", "ip"}
    user_columns = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
    assert not user_columns & {"name", "phone", "email", "aadhaar", "apaar", "dob"}
