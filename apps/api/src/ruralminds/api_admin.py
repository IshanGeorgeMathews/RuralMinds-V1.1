"""Admin routes (only from the server machine itself; see auth.require_role).

Classes, accounts, the answering switches, usage numbers, and the model servers. The model
itself is pinned (rule 3): the admin can see it, pause answering, and restart the servers.
"""

import asyncio
import os
import re
import sqlite3
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from . import auth, stats, uploads
from .api_common import class_label, db
from .auth import User, require_role
from .controls import Controls, load_controls, save_controls

router = APIRouter(prefix="/api/admin", tags=["admin"])
Conn = Annotated[sqlite3.Connection, Depends(db)]
Admin = Annotated[User, Depends(require_role("admin"))]
_USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{1,31}$")


@router.get("/overview")
async def overview(request: Request, user: Admin, conn: Conn, days: int = 14) -> dict:
    counts = conn.execute(
        "SELECT role, count(*) AS n, sum(enabled) AS enabled FROM users GROUP BY role"
    ).fetchall()
    return {
        "usage": stats.usage(conn, max(1, min(days, 90))),
        "accounts": {row["role"]: {"total": row["n"], "enabled": row["enabled"]} for row in counts},
        "books": dict(
            conn.execute("SELECT status, count(*) FROM documents GROUP BY status").fetchall()
        ),
        "unanswered": conn.execute("SELECT count(*) FROM unanswered").fetchone()[0],
        "disk": uploads.disk_report(),
        "model": await stats.model_status(request.app.state.http),
        "controls": asdict(load_controls(conn)),
    }


# ---------- controls and model ----------
class ControlsIn(BaseModel):
    answering_enabled: bool
    allowed_languages: list[Literal["en", "ml"]] = Field(min_length=1)
    disabled_classes: list[int] = Field(default_factory=list)
    max_students: int = Field(ge=1, le=5000)
    max_teachers: int = Field(ge=1, le=500)


@router.post("/controls")
async def set_controls(body: ControlsIn, user: Admin, conn: Conn) -> dict:
    save_controls(conn, Controls(**body.model_dump()))
    return asdict(load_controls(conn))


@router.post("/model/restart")
async def restart_models(user: Admin) -> dict:
    """Stop and start both llama-servers with the pinned settings (same scripts as setup)."""
    if os.name != "nt":
        raise HTTPException(501, detail="admin.restart_windows_only")
    try:
        code = await asyncio.to_thread(_run_restart_scripts)
    except subprocess.TimeoutExpired as error:
        raise HTTPException(504, detail="admin.restart_failed") from error
    if code != 0:
        raise HTTPException(500, detail="admin.restart_failed")
    return {"status": "restarted"}


def _run_restart_scripts() -> int:
    # Output goes to a file, not a pipe: the llama-servers started by the script inherit the
    # script's output handles, so reading a pipe would wait until they exit, i.e. forever.
    script = "./scripts/stop_all.ps1; ./scripts/start_all.ps1 -ModelsOnly"
    Path("logs").mkdir(exist_ok=True)
    with Path("logs/restart.log").open("ab") as log_file:
        return subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            timeout=400,
            check=False,  # the caller turns a non-zero exit into an error message
        ).returncode


# ---------- classes ----------
class ClassIn(BaseModel):
    grade: int = Field(ge=1, le=12)
    section: str = Field(min_length=1, max_length=4, pattern=r"^[A-Za-z0-9]+$")
    medium: Literal["en", "ml"]


@router.get("/classes")
async def list_classes(user: Admin, conn: Conn) -> list[dict]:
    rows = conn.execute(
        "SELECT c.*, (SELECT count(*) FROM users u WHERE u.class_id = c.id) AS students"
        " FROM classes c ORDER BY grade, section"
    ).fetchall()
    return [dict(row) | {"label": class_label(row)} for row in rows]


@router.post("/classes")
async def create_class(body: ClassIn, user: Admin, conn: Conn) -> dict:
    try:
        with conn:
            cursor = conn.execute(
                "INSERT INTO classes (grade, section, medium) VALUES (?,?,?)",
                (body.grade, body.section.upper(), body.medium),
            )
    except sqlite3.IntegrityError as error:
        raise HTTPException(409, detail="class.exists") from error
    return {"id": cursor.lastrowid}


@router.delete("/classes/{class_id}", status_code=204)
async def delete_class(class_id: int, user: Admin, conn: Conn) -> None:
    """Refused while students are still in it, so accounts are never orphaned by accident."""
    if conn.execute("SELECT 1 FROM users WHERE class_id = ?", (class_id,)).fetchone():
        raise HTTPException(409, detail="class.not_empty")
    with conn:
        conn.execute("DELETE FROM classes WHERE id = ?", (class_id,))


# ---------- accounts ----------
class BulkIn(BaseModel):
    class_id: int
    count: int = Field(ge=1, le=100)


class UserIn(BaseModel):
    username: str = Field(min_length=2, max_length=32)
    role: Literal["student", "teacher"]
    class_id: int | None = None
    class_ids: list[int] = Field(default_factory=list)  # classes a teacher teaches


class UserUpdateIn(BaseModel):
    enabled: bool | None = None
    class_id: int | None = None
    class_ids: list[int] | None = None


@router.get("/users")
async def list_users(
    user: Admin,
    conn: Conn,
    role: str | None = None,
    class_id: int | None = None,
    enabled: bool | None = None,
    q: str = "",
) -> list[dict]:
    """Roster search: by role, class, status or username. Not by anything a child did."""
    sql = (
        "SELECT u.id, u.username, u.role, u.class_id, u.enabled, u.created_at,"
        " u.last_login_day, c.grade, c.section FROM users u"
        " LEFT JOIN classes c ON c.id = u.class_id WHERE u.role != 'admin'"
    )
    params: list[object] = []
    for clause, value in (
        ("u.role = ?", role),
        ("u.class_id = ?", class_id),
        ("u.enabled = ?", enabled),
    ):
        if value is not None:
            sql += f" AND {clause}"
            params.append(value)
    if q:
        sql += " AND u.username LIKE ?"
        params.append(f"%{q.strip().lower()}%")
    rows = conn.execute(sql + " ORDER BY u.role, u.username LIMIT 1000", params).fetchall()
    result = []
    for row in rows:
        item = dict(row) | {"class": class_label(row) if row["grade"] else None}
        if row["role"] == "teacher":
            item["class_ids"] = [
                r[0]
                for r in conn.execute(
                    "SELECT class_id FROM teacher_classes WHERE user_id = ?", (row["id"],)
                )
            ]
        result.append(item)
    return result


def _check_capacity(conn: sqlite3.Connection, role: str, adding: int) -> None:
    controls = load_controls(conn)
    cap = controls.max_students if role == "student" else controls.max_teachers
    current = conn.execute("SELECT count(*) FROM users WHERE role = ?", (role,)).fetchone()[0]
    if current + adding > cap:
        raise HTTPException(409, detail="account.limit")


def _insert_user(
    conn: sqlite3.Connection, username: str, role: str, class_id: int | None
) -> tuple[int, str]:
    password = auth.new_password()
    cursor = conn.execute(
        "INSERT INTO users (username, role, class_id, pw_hash) VALUES (?,?,?,?)",
        (username, role, class_id, auth.hash_password(password)),
    )
    return int(cursor.lastrowid), password


def _new_credentials(usernames: list[str]) -> list[tuple[str, str, str]]:
    """(username, password, hash): the slow scrypt part, run in a worker thread."""
    result = []
    for username in usernames:
        password = auth.new_password()
        result.append((username, password, auth.hash_password(password)))
    return result


@router.post("/users/bulk")
async def bulk_students(body: BulkIn, user: Admin, conn: Conn) -> dict:
    """Class 8A x 40 -> 8a-01 ... 8a-40 with printable one-off passwords (shown once only)."""
    klass = conn.execute("SELECT * FROM classes WHERE id = ?", (body.class_id,)).fetchone()
    if klass is None:
        raise HTTPException(404, detail="class.not_found")
    _check_capacity(conn, "student", body.count)
    prefix = class_label(klass).lower()
    taken = {row[0] for row in conn.execute("SELECT username FROM users")}
    usernames, number = [], 0
    while len(usernames) < body.count:
        number += 1
        if f"{prefix}-{number:02d}" not in taken:
            usernames.append(f"{prefix}-{number:02d}")
    credentials = await asyncio.to_thread(_new_credentials, usernames)
    with conn:  # hashing done first, so the transaction itself is quick and never awaits
        conn.executemany(
            "INSERT INTO users (username, role, class_id, pw_hash) VALUES (?, 'student', ?, ?)",
            [(name, body.class_id, pw_hash) for name, _, pw_hash in credentials],
        )
    accounts = [{"username": name, "password": password} for name, password, _ in credentials]
    return {"class": class_label(klass), "accounts": accounts}


@router.post("/users")
async def create_user(body: UserIn, user: Admin, conn: Conn) -> dict:
    username = body.username.strip().lower()
    if not _USERNAME.match(username):
        raise HTTPException(422, detail="account.bad_username")
    if body.role == "student" and body.class_id is None:
        raise HTTPException(422, detail="account.class_required")
    _check_capacity(conn, body.role, 1)
    try:
        with conn:
            class_id = body.class_id if body.role == "student" else None
            user_id, password = _insert_user(conn, username, body.role, class_id)
            if body.role == "teacher":
                _set_teacher_classes(conn, user_id, body.class_ids)
    except sqlite3.IntegrityError as error:
        raise HTTPException(409, detail="account.exists") from error
    return {"username": username, "password": password}


def _set_teacher_classes(conn: sqlite3.Connection, user_id: int, class_ids: list[int]) -> None:
    conn.execute("DELETE FROM teacher_classes WHERE user_id = ?", (user_id,))
    conn.executemany(
        "INSERT INTO teacher_classes VALUES (?, ?)", [(user_id, cid) for cid in set(class_ids)]
    )


def _account(conn: sqlite3.Connection, user_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM users WHERE id = ? AND role != 'admin'", (user_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, detail="account.not_found")
    return row


@router.post("/users/{user_id}")
async def update_user(user_id: int, body: UserUpdateIn, user: Admin, conn: Conn) -> dict:
    account = _account(conn, user_id)
    try:
        with conn:
            if body.enabled is not None:
                conn.execute("UPDATE users SET enabled = ? WHERE id = ?", (body.enabled, user_id))
                if not body.enabled:
                    auth.end_user_sessions(conn, user_id)
            if body.class_id is not None and account["role"] == "student":
                conn.execute("UPDATE users SET class_id = ? WHERE id = ?", (body.class_id, user_id))
            if body.class_ids is not None and account["role"] == "teacher":
                _set_teacher_classes(conn, user_id, body.class_ids)
    except sqlite3.IntegrityError as error:
        raise HTTPException(422, detail="class.not_found") from error
    return {"status": "ok"}


@router.post("/users/{user_id}/reset")
async def reset_password(user_id: int, user: Admin, conn: Conn) -> dict:
    account = _account(conn, user_id)
    password = auth.new_password()
    pw_hash = await asyncio.to_thread(auth.hash_password, password)
    with conn:
        conn.execute("UPDATE users SET pw_hash = ? WHERE id = ?", (pw_hash, user_id))
        auth.end_user_sessions(conn, user_id)
    return {"username": account["username"], "password": password}


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(user_id: int, user: Admin, conn: Conn) -> None:
    _account(conn, user_id)
    with conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
