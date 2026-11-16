"""会话目录表。"""

import time
from datetime import datetime, timezone

from .db import checkpointer, connection, new_thread_id

_last_ts = 0.0


def _now() -> str:
    """当前时间的 ISO 字符串，并保证同一进程内严格递增。"""
    global _last_ts
    now = time.time()
    if now <= _last_ts:
        now = _last_ts + 0.000001
    _last_ts = now
    return datetime.fromtimestamp(now, timezone.utc).isoformat()


def init_conversations_table() -> None:
    """建 conversations 表。用了 IF NOT EXISTS，可以反复调用。"""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS conversations (
            thread_id  TEXT PRIMARY KEY,
            user_id    TEXT NOT NULL,
            title      TEXT NOT NULL DEFAULT '新对话',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_conversations_user
            ON conversations(user_id, updated_at DESC);
        """
    )
    connection.commit()


def auto_title(text: str, limit: int = 18) -> str:
    """用首条消息给会话起个标题，太长就截断。"""
    title = " ".join(text.split())
    return title[:limit] or "新对话"


def create_conversation(
    user_id: str,
    title: str = "新对话",
    thread_id: str | None = None,
) -> str:
    """新建一段会话：写入目录表、返回 thread_id。

    thread_id 不传就自动生成一个新的；
    传了就登记这个指定的 id——用来把"已经存在、但还没进目录表"的会话补进来。
    拿到返回值后，config_for(它) 就能开始聊。
    """
    thread_id = thread_id or new_thread_id()
    now = _now()
    connection.execute(
        "INSERT INTO conversations (thread_id, user_id, title, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (thread_id, user_id, title, now, now),
    )
    connection.commit()
    return thread_id


def get_conversation(thread_id: str) -> dict | None:
    """按 thread_id 查一条会话记录；不存在返回 None。"""
    row = connection.execute(
        "SELECT * FROM conversations WHERE thread_id = ?",
        (thread_id,),
    ).fetchone()
    return dict(row) if row else None


def list_conversations(user_id: str) -> list[dict]:
    """列出某个用户的全部会话，最近更新的排在最前（侧边栏的数据源）。"""
    rows = connection.execute(
        "SELECT * FROM conversations WHERE user_id = ? ORDER BY updated_at DESC",
        (user_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def touch_conversation(thread_id: str) -> None:
    """把 updated_at 刷成现在。每聊完一轮调一次，侧边栏顺序才是对的。"""
    connection.execute(
        "UPDATE conversations SET updated_at = ? WHERE thread_id = ?",
        (_now(), thread_id),
    )
    connection.commit()


def rename_conversation(thread_id: str, title: str) -> None:
    """改标题。"""
    connection.execute(
        "UPDATE conversations SET title = ? WHERE thread_id = ?",
        (title, thread_id),
    )
    connection.commit()


def delete_conversation(thread_id: str) -> None:
    """删掉一段会话。

    两处都要删：目录表里的记录，和 checkpointer 里存的消息。
    只删一边的后果：
      - 只删目录  -> 消息还躺在 checkpoints 表里，数据库越滚越大；
      - 只删消息  -> 侧边栏还留着一条点不开的会话。
    """
    checkpointer.delete_thread(thread_id)
    connection.execute("DELETE FROM conversations WHERE thread_id = ?", (thread_id,))
    connection.commit()


def is_owner(user_id: str, thread_id: str) -> bool:
    """这段会话是不是这个用户的。

    多用户时，任何带着 thread_id 进来的请求都要先过这一关，
    否则 A 用户能直接读 B 用户的聊天记录。
    """
    row = connection.execute(
        "SELECT 1 FROM conversations WHERE thread_id = ? AND user_id = ?",
        (thread_id, user_id),
    ).fetchone()
    return row is not None



