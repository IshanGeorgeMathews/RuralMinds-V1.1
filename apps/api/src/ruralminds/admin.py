"""Server-side admin setup, run on the school computer itself.

    uv run python -m ruralminds.admin init          # first run: admin password + recovery code
    uv run python -m ruralminds.admin reset-admin   # forgot it: needs the printed recovery code
    uv run python -m ruralminds.admin demo          # demo classes and accounts for the judges

The admin account is deliberately not like a student's: it is created here, not in the app,
its password can only be reset with a one-time recovery code printed at setup, and the app
only accepts it from this machine (see auth.py).
"""

import argparse
import getpass
import secrets
import sqlite3

from . import auth
from .config import settings
from .db import connect, init_schema
from .uploads import allocate

MIN_ADMIN_PASSWORD = 10
RECOVERY_KEY = "admin_recovery_hash"


def _ask_new_password() -> str:
    while True:
        first = getpass.getpass(f"New admin password (at least {MIN_ADMIN_PASSWORD} characters): ")
        if len(first) < MIN_ADMIN_PASSWORD:
            print("Too short.")
        elif getpass.getpass("Type it again: ") != first:
            print("They do not match.")
        else:
            return first


def _new_recovery_code(conn: sqlite3.Connection) -> str:
    code = "-".join(secrets.token_hex(3) for _ in range(4))
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?)"
        " ON CONFLICT (key) DO UPDATE SET value = excluded.value",
        (RECOVERY_KEY, f'"{auth.hash_password(code)}"'),
    )
    return code


def _print_code(code: str) -> None:
    print("\nRecovery code (write it down and keep it with the school's records):\n")
    print(f"    {code}\n")
    print("It is shown once. It is the only way to reset the admin password.")


def init(conn: sqlite3.Connection) -> None:
    if conn.execute("SELECT 1 FROM users WHERE role = 'admin'").fetchone():
        raise SystemExit("An admin already exists. Use reset-admin if the password is lost.")
    password = _ask_new_password()
    with conn:
        conn.execute(
            "INSERT INTO users (username, role, pw_hash) VALUES ('admin', 'admin', ?)",
            (auth.hash_password(password),),
        )
        code = _new_recovery_code(conn)
    print("Admin created. Sign in as 'admin' on this computer at http://localhost:8000/admin")
    _print_code(code)


def reset_admin(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (RECOVERY_KEY,)).fetchone()
    if row is None:
        raise SystemExit("No admin yet. Run: python -m ruralminds.admin init")
    code = getpass.getpass("Recovery code: ").strip()
    if not auth.verify_password(code, row["value"].strip('"')):
        raise SystemExit("Wrong recovery code.")
    password = _ask_new_password()
    with conn:
        conn.execute(
            "UPDATE users SET pw_hash = ?, enabled = 1 WHERE role = 'admin'",
            (auth.hash_password(password),),
        )
        conn.execute(
            "DELETE FROM sessions WHERE user_id IN (SELECT id FROM users WHERE role = 'admin')"
        )
        new_code = _new_recovery_code(conn)  # a used code is replaced
    print("Admin password changed.")
    _print_code(new_code)


def demo(conn: sqlite3.Connection) -> None:
    """Class 8A (English medium) and 8B (Malayalam medium) with the two Social Science books,
    one demo student per class and a demo teacher, so nobody waits on setup during a demo."""
    books = dict(conn.execute("SELECT book_id, id FROM documents").fetchall())
    printed = []
    with conn:
        for section, medium, book_id in (("A", "en", "ss8-pt1-en"), ("B", "ml", "ss8-pt1-ml")):
            conn.execute(
                "INSERT OR IGNORE INTO classes (grade, section, medium) VALUES (8, ?, ?)",
                (section, medium),
            )
            class_id = conn.execute(
                "SELECT id FROM classes WHERE grade = 8 AND section = ?", (section,)
            ).fetchone()[0]
            if book_id in books:
                allocate(conn, books[book_id], [class_id])
            printed.append(_demo_user(conn, f"demo-8{section.lower()}", "student", class_id))
        teacher = _demo_user(conn, "demo-teacher", "teacher", None)
        printed.append(teacher)
        conn.execute(
            "INSERT OR IGNORE INTO teacher_classes SELECT u.id, c.id FROM users u, classes c"
            " WHERE u.username = 'demo-teacher' AND c.grade = 8 AND c.section IN ('A', 'B')"
        )
    for username, password in printed:
        print(f"{username:14} {password}")


def _demo_user(
    conn: sqlite3.Connection, username: str, role: str, class_id: int | None
) -> tuple[str, str]:
    password = auth.new_password()
    conn.execute(
        "INSERT INTO users (username, role, class_id, pw_hash) VALUES (?,?,?,?)"
        " ON CONFLICT (username) DO UPDATE SET pw_hash = excluded.pw_hash, enabled = 1",
        (username, role, class_id, auth.hash_password(password)),
    )
    return username, password


def main() -> None:
    parser = argparse.ArgumentParser(description="RuralMinds admin setup (run on the server)")
    parser.add_argument("command", choices=["init", "reset-admin", "demo"])
    args = parser.parse_args()
    conn = connect(settings.db_path)
    init_schema(conn)
    {"init": init, "reset-admin": reset_admin, "demo": demo}[args.command](conn)


if __name__ == "__main__":
    main()
