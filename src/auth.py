"""本地账号与登录会话：密码只存加盐摘要，浏览器只保存HttpOnly随机会话凭证。"""
import hashlib
import hmac
import re
import secrets
import sqlite3
import time
import unicodedata
import uuid
from pathlib import Path
from contextlib import contextmanager

SESSION_SECONDS = 7 * 24 * 60 * 60


class WebError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@contextmanager
def connect(path: Path):
    connection = sqlite3.connect(str(path), timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys = ON')
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def init_users_table(path: Path) -> None:
    with connect(path) as connection:
        connection.executescript("""
        CREATE TABLE IF NOT EXISTS web_users (
            user_id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            username_key TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS web_sessions (
            token_hash TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES web_users(user_id),
            csrf_token TEXT NOT NULL,
            expires_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_web_sessions_user ON web_sessions(user_id);
        """)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    value = hashlib.scrypt(password.encode('utf-8'), salt=salt, n=16384, r=8, p=1)
    return f'scrypt${salt.hex()}${value.hex()}'


def check_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, salt, expected = password_hash.split('$')
        if algorithm != 'scrypt':
            return False
        value = hashlib.scrypt(password.encode('utf-8'), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
        return hmac.compare_digest(value.hex(), expected)
    except (ValueError, TypeError):
        return False


def username_key(username: str) -> str:
    return unicodedata.normalize('NFKC', username).strip().casefold()


def register(path: Path, username: str, password: str) -> dict:
    username = unicodedata.normalize('NFKC', username).strip()
    if not re.fullmatch(r'[\w\-]{3,32}', username, re.UNICODE):
        raise WebError(400, '用户名需为3～32个字母、数字、中文、下划线或短横线。')
    if not 8 <= len(password) <= 128:
        raise WebError(400, '密码长度需为8～128个字符。')
    user_id = str(uuid.uuid4())
    password_hash = hash_password(password)
    try:
        with connect(path) as connection:
            connection.execute('INSERT INTO web_users VALUES (?, ?, ?, ?, ?)',
                               (user_id, username, username_key(username), password_hash, time.time()))
    except sqlite3.IntegrityError:
        raise WebError(409, '这个用户名已被使用，请换一个。') from None
    return {'user_id':user_id, 'username':username}


def login(path: Path, username: str, password: str) -> dict:
    if len(password) > 128:
        raise WebError(401, '用户名或密码不正确。')
    with connect(path) as connection:
        row = connection.execute('SELECT * FROM web_users WHERE username_key = ?',
                                 (username_key(username),)).fetchone()
    # 不存在的账号也执行一次密码推导，避免快速分支泄露用户名是否注册。
    candidate = row['password_hash'] if row else 'scrypt$' + '00'*16 + '$' + '00'*64
    if not check_password(password, candidate) or row is None:
        raise WebError(401, '用户名或密码不正确。')
    return {'user_id':row['user_id'], 'username':row['username']}


def create_session(path: Path, user_id: str) -> tuple[str, str]:
    token, csrf_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    with connect(path) as connection:
        connection.execute('DELETE FROM web_sessions WHERE expires_at <= ?', (time.time(),))
        connection.execute('INSERT INTO web_sessions VALUES (?, ?, ?, ?)',
                           (hashlib.sha256(token.encode()).hexdigest(), user_id, csrf_token, time.time()+SESSION_SECONDS))
    return token, csrf_token


def get_session(path: Path, token: str) -> dict | None:
    if not token or len(token) > 128:
        return None
    with connect(path) as connection:
        row = connection.execute('SELECT s.user_id, u.username, s.csrf_token FROM web_sessions s '
                                 'JOIN web_users u ON u.user_id=s.user_id '
                                 'WHERE s.token_hash=? AND s.expires_at>?',
                                 (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
    return dict(row) if row else None


def logout(path: Path, token: str) -> None:
    with connect(path) as connection:
        connection.execute('DELETE FROM web_sessions WHERE token_hash=?',
                           (hashlib.sha256(token.encode()).hexdigest(),))
