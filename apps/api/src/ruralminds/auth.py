"""Accounts, passwords and sessions, standard library only.

Accounts are created by the admin (no self sign-up) and hold a username, a role and, for a
student, a class. Nothing else about the child is stored, and no other table points at an
account, so questions can never be traced back to a student.

The admin is different: admin requests are only accepted from the server machine itself
(127.0.0.1), so a phone on the school Wi-Fi cannot even try the admin password.
"""

import hashlib
import hmac
import secrets
import sqlite3
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import HTTPException, Request

from .config import settings

COOKIE = "rm_session"
# scrypt cost: 16 MB of memory per hash makes offline guessing of a stolen database slow,
# while one login still takes well under a second on a laptop CPU.
_SCRYPT = {"n": 2**14, "r": 8, "p": 1}
# No 0/O, 1/l/I: passwords are read off a printed slip by a child.
_PASSWORD_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
_LOCAL_HOSTS = {"127.0.0.1", "::1"}
ROLES = ("student", "teacher", "admin")


@dataclass
class User:
    id: int
    username: str
    role: str
    class_id: int | None


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **_SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), dklen=32, **_SCRYPT)
    return hmac.compare_digest(digest.hex(), digest_hex)


def new_password(length: int = 6) -> str:
    return "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(length))


# A real hash to check against when the username does not exist, so a wrong username and a
# wrong password take the same time and cannot be told apart.
_DUMMY_HASH = hash_password(secrets.token_hex(8))


def find_login(conn: sqlite3.Connection, username: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, username, role, class_id, pw_hash, enabled FROM users WHERE username = ?",
        (username.strip(),),
    ).fetchone()


def check_login(row: sqlite3.Row | None, password: str) -> User | None:
    """The slow scrypt part, with no database access: safe to run in a worker thread. The
    shared connection must stay on the event loop (concurrent logins through it from threads
    failed with 'bad parameter or other API misuse' in the 19 Oct bench)."""
    if row is None:
        verify_password(password, _DUMMY_HASH)
        return None
    if not verify_password(password, row["pw_hash"]) or not row["enabled"]:
        return None
    return User(row["id"], row["username"], row["role"], row["class_id"])


def authenticate(conn: sqlite3.Connection, username: str, password: str) -> User | None:
    return check_login(find_login(conn, username), password)


class LoginThrottle:
    """Too many wrong passwords for one username -> wait. In memory: a restart clears it,
    which is fine for a classroom server."""

    def __init__(self, max_failures: int, window_seconds: float) -> None:
        self.max_failures = max_failures
        self.window = window_seconds
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def _recent(self, username: str, now: float) -> deque[float]:
        failures = self._failures[username.casefold()]
        while failures and now - failures[0] > self.window:
            failures.popleft()
        return failures

    def blocked(self, username: str, now: float | None = None) -> bool:
        return len(self._recent(username, now or time.time())) >= self.max_failures

    def failed(self, username: str, now: float | None = None) -> None:
        now = now or time.time()
        self._recent(username, now).append(now)

    def succeeded(self, username: str) -> None:
        self._failures.pop(username.casefold(), None)


def _token_hash(token: str) -> str:
    # Only the hash is stored, so a copied database file holds no usable session.
    return hashlib.sha256(token.encode()).hexdigest()


def idle_limit(role: str) -> int:
    """Students share phones, so their sessions end soon after they stop using it."""
    minutes = {
        "student": settings.student_idle_minutes,
        "teacher": settings.teacher_idle_minutes,
        "admin": settings.admin_idle_minutes,
    }[role]
    return minutes * 60


def create_session(conn: sqlite3.Connection, user: User, now: float | None = None) -> str:
    now = now or time.time()
    token = secrets.token_urlsafe(32)
    with conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
        conn.execute(
            "INSERT INTO sessions VALUES (?,?,?,?,?)",
            (
                _token_hash(token),
                user.id,
                now + settings.session_max_hours * 3600,
                idle_limit(user.role),
                now,
            ),
        )
        conn.execute(
            "UPDATE users SET last_login_day = date('now', 'localtime') WHERE id = ?", (user.id,)
        )
    return token


def session_user(conn: sqlite3.Connection, token: str, now: float | None = None) -> User | None:
    now = now or time.time()
    row = conn.execute(
        "SELECT s.expires_at, s.idle_seconds, s.last_seen, u.id, u.username, u.role,"
        " u.class_id, u.enabled FROM sessions s JOIN users u ON u.id = s.user_id"
        " WHERE s.token_hash = ?",
        (_token_hash(token),),
    ).fetchone()
    if row is None:
        return None
    expired = now > row["expires_at"] or now - row["last_seen"] > row["idle_seconds"]
    if expired or not row["enabled"]:
        end_session(conn, token)
        return None
    if now - row["last_seen"] > 30:  # avoid a database write on every request
        with conn:
            conn.execute(
                "UPDATE sessions SET last_seen = ? WHERE token_hash = ?", (now, _token_hash(token))
            )
    return User(row["id"], row["username"], row["role"], row["class_id"])


def end_session(conn: sqlite3.Connection, token: str) -> None:
    with conn:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))


def end_user_sessions(conn: sqlite3.Connection, user_id: int) -> None:
    """After a password reset or disabling an account. Caller owns the transaction."""
    conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))


def is_local(request: Request) -> bool:
    return request.client is not None and request.client.host in _LOCAL_HOSTS


def current_user(request: Request) -> User | None:
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    return session_user(request.app.state.db, token)


def require_role(*roles: str) -> Callable[[Request], User]:
    """Dependency: the signed-in user, if their role is allowed; admin only from this machine."""

    # async on purpose: FastAPI runs a plain `def` dependency in a worker thread, and this one
    # reads the shared sqlite connection; concurrent requests then used it from several threads
    # at once ('bad parameter or other API misuse', bench 19 Oct). On the event loop they queue.
    async def dependency(request: Request) -> User:
        user = current_user(request)
        if user is None:
            raise HTTPException(401, detail="auth.required")
        if user.role not in roles:
            raise HTTPException(403, detail="auth.forbidden")
        if user.role == "admin" and not is_local(request):
            raise HTTPException(403, detail="auth.admin_local_only")
        return user

    return dependency
