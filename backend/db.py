import os
import sqlite3
import hashlib
import secrets
import datetime as dt
from pathlib import Path
from contextlib import contextmanager

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("ULP_DB_PATH", BASE_DIR / "ulp.db"))

_PBKDF2_ROUNDS = 200_000


@contextmanager
def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                username    TEXT PRIMARY KEY,
                pwd_hash    TEXT NOT NULL,
                pwd_salt    TEXT NOT NULL,
                saved_grade INTEGER DEFAULT 5,
                xp          INTEGER DEFAULT 0,
                level       INTEGER DEFAULT 1,
                streak      INTEGER DEFAULT 0,
                last_active TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                token      TEXT PRIMARY KEY,
                username   TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS attempts (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                username       TEXT,
                subject        TEXT,
                topic          TEXT,
                question       TEXT,
                user_answer    TEXT,
                correct_answer TEXT,
                is_correct     INTEGER,
                score          REAL,
                created_at     TEXT
            )
        """)


def _hash_password(password: str, salt: str) -> str:
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), _PBKDF2_ROUNDS
    )
    return dk.hex()


def validate_password(password: str) -> str | None:
    import re
    if len(password) < 8:
        return "Пароль должен содержать минимум 8 символов"
    if not re.search(r"[A-ZА-Я]", password):
        return "Пароль должен содержать заглавную букву"
    if not re.search(r"[a-zа-я]", password):
        return "Пароль должен содержать строчную букву"
    if not re.search(r"[0-9]", password):
        return "Пароль должен содержать цифру"
    return None


def _now() -> str:
    return dt.datetime.utcnow().isoformat()


def create_user(username: str, password: str) -> dict:
    username = username.strip()
    if not username:
        raise ValueError("Логин не может быть пустым")
    salt = secrets.token_hex(16)
    pwd_hash = _hash_password(password, salt)
    with _conn() as c:
        exists = c.execute(
            "SELECT 1 FROM users WHERE username = ?", (username,)
        ).fetchone()
        if exists:
            raise ValueError("Пользователь уже существует")
        c.execute(
            """INSERT INTO users (username, pwd_hash, pwd_salt, saved_grade,
                                  xp, level, streak, last_active)
               VALUES (?, ?, ?, 5, 0, 1, 0, ?)""",
            (username, pwd_hash, salt, _now()),
        )
    return get_user(username)


def verify_user(username: str, password: str) -> bool:
    with _conn() as c:
        row = c.execute(
            "SELECT pwd_hash, pwd_salt FROM users WHERE username = ?", (username,)
        ).fetchone()
    if not row:
        return False
    return secrets.compare_digest(
        _hash_password(password, row["pwd_salt"]), row["pwd_hash"]
    )


def get_user(username: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            """SELECT username, saved_grade, xp, level, streak, last_active
               FROM users WHERE username = ?""",
            (username,),
        ).fetchone()
    return dict(row) if row else None


def save_grade(username: str, grade: int) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE users SET saved_grade = ? WHERE username = ?", (grade, username)
        )


def create_session(username: str) -> str:
    token = secrets.token_urlsafe(32)
    with _conn() as c:
        c.execute(
            "INSERT INTO sessions (token, username, created_at) VALUES (?, ?, ?)",
            (token, username, _now()),
        )
    return token


def session_user(token: str) -> str | None:
    if not token:
        return None
    with _conn() as c:
        row = c.execute(
            "SELECT username FROM sessions WHERE token = ?", (token,)
        ).fetchone()
    return row["username"] if row else None


def delete_session(token: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM sessions WHERE token = ?", (token,))


def _level_for_xp(xp: int) -> int:

    level = 1
    need = 100
    while xp >= need:
        xp -= need
        level += 1
        need = int(need * 1.4)
    return level


def record_attempt(
    username: str,
    subject: str,
    topic: str,
    question: str,
    user_answer: str,
    correct_answer: str,
    is_correct: bool,
    score: float,
) -> dict:
    gained = 0
    with _conn() as c:
        c.execute(
            """INSERT INTO attempts (username, subject, topic, question,
                   user_answer, correct_answer, is_correct, score, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (username, subject, topic, question, user_answer,
             correct_answer, int(is_correct), score, _now()),
        )

        row = c.execute(
            "SELECT xp, streak, last_active FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        xp = row["xp"]
        streak = row["streak"]

        if is_correct:
            gained = 10 + int(15 * score)
            streak += 1
            gained += min(streak, 10)
        else:
            streak = 0

        xp += gained
        level = _level_for_xp(xp)

        c.execute(
            """UPDATE users SET xp = ?, level = ?, streak = ?, last_active = ?
               WHERE username = ?""",
            (xp, level, streak, _now(), username),
        )

    progress = get_user(username) or {}
    progress["xp_gained"] = gained
    return progress


def stats(username: str) -> dict:
    with _conn() as c:
        total = c.execute(
            "SELECT COUNT(*) n FROM attempts WHERE username = ?", (username,)
        ).fetchone()["n"]
        correct = c.execute(
            "SELECT COUNT(*) n FROM attempts WHERE username = ? AND is_correct = 1",
            (username,),
        ).fetchone()["n"]
        by_subject = c.execute(
            """SELECT subject,
                      COUNT(*) total,
                      SUM(is_correct) correct
               FROM attempts WHERE username = ?
               GROUP BY subject ORDER BY total DESC""",
            (username,),
        ).fetchall()
    return {
        "total": total,
        "correct": correct,
        "accuracy": round(correct / total, 3) if total else 0.0,
        "by_subject": [dict(r) for r in by_subject],
    }
