"""JobPolit本地网页入口：python -m src.web，或直接运行 python -m src.main。"""
import argparse
import hmac
import json
import logging
import re
import threading
import time
import webbrowser
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from contextlib import contextmanager
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast
from urllib.parse import unquote, urlsplit

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from openai import APITimeoutError

from . import auth, memory, profiles
from .agent import build_agent, config_for
from .core import extract_profile
from .db import DB_PATH
from .schemas import UserProfile

logger = logging.getLogger(__name__)

STATIC = Path(__file__).resolve().parent / "static"
COOKIE_NAME = "jobpolit_session"
MAX_BODY = 160_000
WAIT_SECONDS = 120
RATE_WINDOW = 900
RATE_LIMIT = 15

ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/assets/app.css": ("app.css", "text/css; charset=utf-8"),
    "/assets/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
}

SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    ),
}

WEB_TABLES = """
CREATE TABLE IF NOT EXISTS web_messages (
    message_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL,
    role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_web_messages_thread ON web_messages(thread_id, created_at);
CREATE TABLE IF NOT EXISTS web_requests (
    thread_id TEXT NOT NULL, request_id TEXT NOT NULL,
    message TEXT NOT NULL, status TEXT NOT NULL, answer TEXT,
    PRIMARY KEY (thread_id, request_id)
);
"""


def text_of(content) -> str:
    """把模型返回的内容块统一成纯文本。"""
    if isinstance(content, list):
        return "\n".join(block.get("text", "") if isinstance(block, dict) else str(block) for block in content)
    return content if isinstance(content, str) else str(content)


class Application:
    def __init__(self, path=DB_PATH, agent_factory=build_agent, extractor=extract_profile):
        self.path = Path(path)
        self.agent_factory = agent_factory
        self.extractor = extractor
        self.agent = None
        self.agent_lock = threading.Lock()
        self.db_lock = threading.RLock()
        self.locks_lock = threading.Lock()
        self.thread_locks = {}
        self.profile_locks = {}
        self.rate_lock = threading.Lock()
        self.attempts = defaultdict(deque)
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="jobpolit")
        self.slots = threading.BoundedSemaphore(4)
        self.demo = False
        auth.init_users_table(self.path)
        profiles.init_profiles_table(self.path)
        with self.db_lock:
            memory.init_conversations_table()
        with auth.connect(self.path) as connection:
            connection.executescript(WEB_TABLES)

    def close(self):
        self.executor.shutdown(wait=False, cancel_futures=True)

    def lock_named(self, name, profile=False):
        with self.locks_lock:
            locks = self.profile_locks if profile else self.thread_locks
            return locks.setdefault(name, threading.Lock())

    @contextmanager
    def exclusive(self, name, busy_message, profile=False):
        """同一会话或同一用户同时只跑一件事；占用中直接报 409。"""
        lock = self.lock_named(name, profile)
        if not lock.acquire(blocking=False):
            raise auth.WebError(409, busy_message)
        try:
            yield
        finally:
            lock.release()

    def check_rate(self, address):
        """同一来源 15 分钟内最多 15 次登录或注册尝试。"""
        now = time.monotonic()
        with self.rate_lock:
            if len(self.attempts) > 1000:
                self.attempts = defaultdict(deque, {
                    key: entries for key, entries in self.attempts.items()
                    if entries and now - entries[-1] <= RATE_WINDOW
                })
            entries = self.attempts[address]
            while entries and now - entries[0] > RATE_WINDOW:
                entries.popleft()
            if len(entries) >= RATE_LIMIT:
                raise auth.WebError(429, "尝试次数较多，请15分钟后再试。")
            entries.append(now)

    def conversation(self, user_id, thread_id):
        """校验归属并返回会话；不是本人的一律按不存在处理。"""
        with self.db_lock:
            if not memory.is_owner(user_id, thread_id):
                raise auth.WebError(404, "会话不存在或你无权访问。")
            return memory.get_conversation(thread_id)

    def conversations(self, user_id):
        with self.db_lock:
            return memory.list_conversations(user_id)

    def create_conversation(self, user_id):
        with self.db_lock:
            return memory.get_conversation(memory.create_conversation(user_id=user_id))

    def rename_conversation(self, user_id, thread_id, title):
        self.conversation(user_id, thread_id)
        title = title.strip()
        if not 0 < len(title) <= 80:
            raise auth.WebError(400, "标题需为1～80个字符。")
        with self.db_lock:
            memory.rename_conversation(thread_id, title)
            return memory.get_conversation(thread_id)

    def delete_conversation(self, user_id, thread_id):
        self.conversation(user_id, thread_id)
        with self.exclusive(thread_id, "这段会话正在生成回答，请完成后再删除。"):
            with self.db_lock:
                memory.delete_conversation(thread_id)
            with auth.connect(self.path) as connection:
                connection.execute("DELETE FROM web_messages WHERE thread_id=?", (thread_id,))
                connection.execute("DELETE FROM web_requests WHERE thread_id=?", (thread_id,))

    def messages(self, user_id, thread_id):
        """读取会话消息；先校验归属，避免被非本人调用。"""
        self.conversation(user_id, thread_id)
        with auth.connect(self.path) as connection:
            rows = connection.execute(
                "SELECT message_id, role, content, created_at FROM web_messages "
                "WHERE thread_id=? ORDER BY created_at, rowid",
                (thread_id,),
            ).fetchall()
        return [dict(row) for row in rows] if rows else self.checkpoint_messages(thread_id)

    def checkpoint_messages(self, thread_id):
        """网页消息表出现之前的旧会话，从 checkpoint 里读出可显示的历史。"""
        with self.db_lock:
            state = memory.checkpointer.get(cast(RunnableConfig, config_for(thread_id))) or {}
        history = state.get("channel_values", {}).get("messages", [])
        return [
            {
                "message_id": message.id or str(index),
                "role": "user" if message.type == "human" else "assistant",
                "content": text_of(message.content),
                "created_at": "",
            }
            for index, message in enumerate(history)
            if getattr(message, "type", "") in ("human", "ai")
            and message.content
            and not getattr(message, "tool_calls", None)
        ]

    def submit_profile(self, user_id, text):
        text = text.strip()
        if not 0 < len(text) <= 30_000:
            raise auth.WebError(400, "请输入简历内容，最多30,000个字符。")
        with self.exclusive(user_id, "简历正在解析，请稍候。", profile=True):
            profile = self.extractor(text)
            if not isinstance(profile, UserProfile):
                profile = UserProfile.model_validate(profile)
            with self.db_lock:
                return profiles.save_profile(self.path, user_id, text, profile)

    def chat(self, user_id, thread_id, message, request_id):
        self.conversation(user_id, thread_id)
        message = message.strip()
        if not 0 < len(message) <= 20_000:
            raise auth.WebError(400, "消息需为1～20,000个字符。")
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", request_id):
            raise auth.WebError(400, "消息标识无效，请刷新页面重试。")
        with self.exclusive(thread_id, "当前会话正在生成回答，请稍候。"):
            # 等锁期间会话可能已被删除，拿到锁后再确认一次。
            self.conversation(user_id, thread_id)
            try:
                answer = self.reply(user_id, thread_id, message, request_id)
            except Exception:
                self.set_status(thread_id, request_id, "failed")
                raise
            finally:
                with self.db_lock:
                    memory.touch_conversation(thread_id)
        return {"answer": answer, "request_id": request_id}

    def reply(self, user_id, thread_id, message, request_id):
        """幂等生成一轮回答：同一 request_id 重发直接返回上次的答案。"""
        cached = self.begin_request(user_id, thread_id, message, request_id)
        if cached is not None:
            return cached
        profile = profiles.get_profile(self.path, user_id)["profile"]
        state = self.get_agent().invoke(
            {"messages": [HumanMessage(content=message, id=request_id)], "profile": profile},
            config=cast(RunnableConfig, config_for(thread_id)),
        )
        answer = self.final_answer(state.get("messages", []))
        if not answer.strip():
            raise auth.WebError(502, "模型没有返回可显示的回答，请重试。")
        with auth.connect(self.path) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO web_messages VALUES (?,?,?,?,?)",
                (f"{thread_id}:{request_id}:assistant", thread_id, "assistant", answer, memory._now()),
            )
            connection.execute(
                "UPDATE web_requests SET status=?, answer=? WHERE thread_id=? AND request_id=?",
                ("completed", answer, thread_id, request_id),
            )
        return answer

    def begin_request(self, user_id, thread_id, message, request_id):
        """登记这次请求；已完成则返回上次的答案，否则返回 None。"""
        with auth.connect(self.path) as connection:
            row = connection.execute(
                "SELECT message, status, answer FROM web_requests WHERE thread_id=? AND request_id=?",
                (thread_id, request_id),
            ).fetchone()
            if row and row["message"] != message:
                raise auth.WebError(409, "同一个消息标识不能用于不同内容。")
            if row and row["status"] == "completed":
                return row["answer"]
            if row is None:
                self.register_request(connection, user_id, thread_id, message, request_id)
            else:
                connection.execute(
                    "UPDATE web_requests SET status=? WHERE thread_id=? AND request_id=?",
                    ("pending", thread_id, request_id),
                )
        return None

    def register_request(self, connection, user_id, thread_id, message, request_id):
        """新出现的 request_id：必要时起标题、迁移旧历史，写入用户消息和 pending 状态。"""
        history = self.messages(user_id, thread_id)
        if not history:
            with self.db_lock:
                if (memory.get_conversation(thread_id) or {}).get("title") == "新对话":
                    memory.rename_conversation(thread_id, memory.auto_title(message))
        if not connection.execute("SELECT 1 FROM web_messages WHERE thread_id=? LIMIT 1", (thread_id,)).fetchone():
            for index, item in enumerate(history):
                connection.execute(
                    "INSERT OR IGNORE INTO web_messages VALUES (?,?,?,?,?)",
                    (f"{thread_id}:legacy:{index}", thread_id, item["role"], item["content"], memory._now()),
                )
        connection.execute(
            "INSERT INTO web_messages VALUES (?,?,?,?,?)",
            (f"{thread_id}:{request_id}:user", thread_id, "user", message, memory._now()),
        )
        connection.execute(
            "INSERT INTO web_requests VALUES (?,?,?,?,?)",
            (thread_id, request_id, message, "pending", None),
        )

    def set_status(self, thread_id, request_id, status):
        with auth.connect(self.path) as connection:
            connection.execute(
                "UPDATE web_requests SET status=? WHERE thread_id=? AND request_id=? AND status!=?",
                (status, thread_id, request_id, "completed"),
            )

    @staticmethod
    def final_answer(messages) -> str:
        """取最后一条有内容的纯文本 AI 消息。"""
        for message in reversed(messages):
            if getattr(message, "type", "") == "ai" and message.content and not getattr(message, "tool_calls", None):
                return text_of(message.content)
        return ""

    def get_agent(self):
        with self.agent_lock:
            self.agent = self.agent or self.agent_factory()
            return self.agent

    def expensive(self, function, *args):
        """把慢任务丢进线程池，最多等 120 秒；超时不假装取消任务。"""
        if not self.slots.acquire(blocking=False):
            raise auth.WebError(503, "服务正在处理其他任务，请稍后再试。")
        future = self.executor.submit(self.run_slot, function, args)
        try:
            return future.result(timeout=WAIT_SECONDS)
        except FutureTimeout:
            if future.done():
                raise auth.WebError(502, "模型或搜索服务超时，请稍后重试。") from None
            raise auth.WebError(504, "处理时间较长，任务仍在后台进行。请稍后刷新查看，不要重复提交。") from None

    def run_slot(self, function, args):
        try:
            return function(*args)
        finally:
            self.slots.release()


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, app):
        self.app = app
        super().__init__(address, Handler)

    def server_close(self):
        super().server_close()
        self.app.close()


class Handler(BaseHTTPRequestHandler):
    server_version = "JobPolit"

    def do_GET(self):
        self.dispatch()

    do_POST = do_PATCH = do_DELETE = do_GET

    def log_message(self, format, *args):
        logger.info("%s %s", self.command, urlsplit(self.path).path)

    def dispatch(self):
        try:
            self.route()
        except auth.WebError as exc:
            self.respond(exc.status, {"error": exc.message})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except APITimeoutError:
            self.respond(504, {"error": "模型请求超时，已结束本次任务，请稍后重试。"})
        except Exception as exc:
            # 异常消息可能带服务商信息，只记类型。
            logger.error("Request failed: %s", type(exc).__name__)
            self.respond(502, {"error": "服务暂时未完成请求，请检查模型/搜索配置后重试。已有简历和会话不会因此被清空。"})

    def route(self):
        app = cast(Server, self.server).app
        path = unquote(urlsplit(self.path).path)
        self.check_origin()
        if path == "/api/health" and self.command == "GET":
            return self.respond(200, {"ok": True, "demo": app.demo})
        if not path.startswith("/api/"):
            return self.serve_asset(path)
        if path in ("/api/auth/login", "/api/auth/register") and self.command == "POST":
            return self.sign_in(app, path)
        session = auth.get_session(app.path, self.token())
        if session is None:
            raise auth.WebError(401, "请先登录。")
        if self.command != "GET":
            self.check_csrf(session)
        user_id = session["user_id"]
        if path == "/api/auth/me" and self.command == "GET":
            return self.respond(200, {
                "user": {"user_id": user_id, "username": session["username"]},
                "csrf_token": session["csrf_token"],
            })
        if path == "/api/auth/logout" and self.command == "POST":
            auth.logout(app.path, self.token())
            return self.respond(200, {"ok": True}, f"{COOKIE_NAME}=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0")
        if path == "/api/profile" and self.command == "GET":
            return self.respond(200, profiles.get_profile(app.path, user_id))
        if path == "/api/profile" and self.command == "POST":
            return self.respond(200, app.expensive(app.submit_profile, user_id, self.field(self.body(), "text")))
        if path == "/api/conversations" and self.command == "GET":
            return self.respond(200, {"conversations": app.conversations(user_id)})
        if path == "/api/conversations" and self.command == "POST":
            self.body()
            return self.respond(201, {"conversation": app.create_conversation(user_id)})
        return self.thread_route(app, user_id, path)

    def thread_route(self, app, user_id, path):
        match = re.fullmatch(r"/api/conversations/([A-Za-z0-9_-]{1,80})(/messages)?", path)
        if not match:
            raise auth.WebError(404, "接口不存在。")
        thread_id, messages_path = match.groups()
        if messages_path and self.command == "GET":
            return self.respond(200, {"conversation": app.conversation(user_id, thread_id),
                                      "messages": app.messages(user_id, thread_id)})
        if messages_path and self.command == "POST":
            body = self.body()
            answer = app.expensive(app.chat, user_id, thread_id,
                                   self.field(body, "message"), self.field(body, "request_id"))
            return self.respond(200, answer)
        if not messages_path and self.command == "PATCH":
            title = self.field(self.body(), "title")
            return self.respond(200, {"conversation": app.rename_conversation(user_id, thread_id, title)})
        if not messages_path and self.command == "DELETE":
            app.delete_conversation(user_id, thread_id)
            return self.respond(200, {"ok": True})
        raise auth.WebError(405, "不支持此操作。")

    def sign_in(self, app, path):
        app.check_rate(self.client_address[0])
        body = self.body()
        username, password = self.field(body, "username"), self.field(body, "password")
        if len(username) > 64 or len(password) > 128:
            raise auth.WebError(400, "用户名或密码过长。")
        action = auth.login if path.endswith("/login") else auth.register
        user = action(app.path, username, password)
        token, csrf_token = auth.create_session(app.path, user["user_id"])
        self.respond(200, {"user": user, "csrf_token": csrf_token},
                     f"{COOKIE_NAME}={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={auth.SESSION_SECONDS}")

    def serve_asset(self, path):
        if self.command != "GET":
            raise auth.WebError(405, "不支持此操作。")
        asset = ASSETS.get(path)
        if asset is None:
            raise auth.WebError(404, "页面不存在。")
        name, content_type = asset
        self.send_bytes(200, (STATIC / name).read_bytes(), content_type)

    def check_origin(self):
        """只接受本机地址，并拒绝跨站写请求。"""
        host = self.headers.get("Host", "")
        port = cast(Server, self.server).server_port
        if host not in {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}:
            raise auth.WebError(403, "请从本机localhost地址访问。")
        origin = self.headers.get("Origin")
        if self.command != "GET" and origin and origin != f"http://{host}":
            raise auth.WebError(403, "请求来源无效，请刷新页面。")

    def check_csrf(self, session):
        token = self.headers.get("X-CSRF-Token", "")
        if not token or not hmac.compare_digest(token, session["csrf_token"]):
            raise auth.WebError(403, "会话校验失败，请刷新页面。")

    def send_bytes(self, status, body, content_type, cookie=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def respond(self, status, value, cookie=None):
        self.send_bytes(status, json.dumps(value, ensure_ascii=False).encode("utf-8"),
                        "application/json; charset=utf-8", cookie)

    def token(self):
        cookie = SimpleCookie()
        cookie.load(self.headers.get("Cookie", ""))
        return cookie[COOKIE_NAME].value if COOKIE_NAME in cookie else ""

    def body(self):
        if self.headers.get("Transfer-Encoding"):
            raise auth.WebError(400, "不支持此请求编码。")
        length = self.headers.get("Content-Length", "0")
        if not length.isdigit():
            raise auth.WebError(400, "请求长度无效。")
        if int(length) > MAX_BODY:
            raise auth.WebError(413, "提交内容过长。")
        if self.headers.get_content_type() != "application/json":
            raise auth.WebError(415, "请使用JSON提交。")
        try:
            value = json.loads(self.rfile.read(int(length)))
        except ValueError:
            raise auth.WebError(400, "请求内容不是有效JSON。") from None
        if not isinstance(value, dict):
            raise auth.WebError(400, "请求内容需为JSON对象。")
        return value

    @staticmethod
    def field(body, name):
        value = body.get(name, "")
        if not isinstance(value, str):
            raise auth.WebError(400, f"{name}需为字符串。")
        return value


def main():
    parser = argparse.ArgumentParser(description="JobPolit 本地网页")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("端口需为1～65535")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    app = Application()
    try:
        server = Server(("127.0.0.1", args.port), app)
    except OSError:
        app.close()
        parser.error(f"端口{args.port}无法使用，请通过--port换一个端口。")
    url = f"http://127.0.0.1:{args.port}"
    print(f"JobPolit 已启动：{url}\n按 Ctrl+C 停止。", flush=True)
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
