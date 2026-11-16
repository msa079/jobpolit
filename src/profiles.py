"""独立简历入口。一次提交完整替换画像"""
import json
from pathlib import Path

from .auth import connect
from .memory import _now
from .schemas import UserProfile


def init_profiles_table(path: Path) -> None:
    with connect(path) as connection:
        connection.execute("""CREATE TABLE IF NOT EXISTS web_profiles (
            user_id TEXT PRIMARY KEY REFERENCES web_users(user_id),
            text TEXT NOT NULL,
            profile TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""")


def get_profile(path: Path, user_id: str) -> dict:
    with connect(path) as connection:
        row = connection.execute('SELECT text, profile, updated_at FROM web_profiles WHERE user_id=?',
                                 (user_id,)).fetchone()
    if row is None:
        return {'text':'', 'profile':UserProfile().model_dump(), 'updated_at':None}
    return {'text':row['text'], 'profile':json.loads(row['profile']), 'updated_at':row['updated_at']}


def save_profile(path: Path, user_id: str, text: str, profile: UserProfile) -> dict:
    with connect(path) as connection:
        connection.execute('INSERT INTO web_profiles VALUES (?, ?, ?, ?) '
                           'ON CONFLICT(user_id) DO UPDATE SET text=excluded.text, '
                           'profile=excluded.profile, updated_at=excluded.updated_at',
                           (user_id, text, profile.model_dump_json(), _now()))
    return get_profile(path, user_id)
