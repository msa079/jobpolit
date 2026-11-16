import os
import sqlite3
import uuid
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver


DB_PATH = Path(
    os.getenv("JOBPOLIT_DB")
    or Path(__file__).resolve().parent.parent / "data" / "checkpoint.db"
)
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

connection = sqlite3.connect(str(DB_PATH), check_same_thread=False)
connection.row_factory = sqlite3.Row
checkpointer = SqliteSaver(connection)
checkpointer.setup()


def new_checkpointer() -> SqliteSaver:
    """给 Agent 创建独立连接，避免与侧边栏操作共享事务。"""
    connection = sqlite3.connect(str(DB_PATH), timeout=15, check_same_thread=False)
    checkpointer = SqliteSaver(connection)
    checkpointer.setup()
    return checkpointer


def new_thread_id() -> str:
    """生成一个新的会话 ID。

    会话 ID 是 conversations 表的主键，也是 checkpoints 表主键的第一部分，
    
    """
    return str(uuid.uuid4())
